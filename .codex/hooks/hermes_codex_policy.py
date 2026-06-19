#!/usr/bin/env python3
"""Hermes Bot Codex hook policy.

Implements repository guard rails through current Codex hooks.
PreToolUse blocks return hookSpecificOutput.permissionDecision="deny".
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


API_KEY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OpenAI-style sk key", re.compile(r"sk-[A-Za-z0-9]{40,}")),
    ("GitHub personal access token", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
]

SENSITIVE_FILE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    *API_KEY_PATTERNS,
    ("private key block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
]

DANGEROUS_RM_ROOTS = (
    "/",
    "/usr/local/lib/hermes-agent",
    "/root/.hermes",
)

TEMP_BLOCKLIST = ".codex/hooks/temp-block-patterns.txt"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    event = str(payload.get("hook_event_name") or "")
    if event == "PreToolUse":
        reason = pre_tool_use_violation(payload)
        if reason:
            print(json.dumps(pretool_deny(reason), ensure_ascii=False))
    elif event == "PostToolUse":
        reason = post_tool_use_violation(payload)
        if reason:
            print(json.dumps(posttool_block(reason), ensure_ascii=False))
    return 0


def pretool_deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def posttool_block(reason: str) -> dict[str, Any]:
    return {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": reason,
        },
    }


def pre_tool_use_violation(payload: dict[str, Any]) -> str | None:
    tool_name = str(payload.get("tool_name") or "")
    command = tool_command(payload)

    temp_reason = temp_block_violation(payload, command)
    if temp_reason:
        return temp_reason

    if tool_name == "Bash":
        return bash_violation(payload, command)

    if is_edit_tool(tool_name):
        return edit_violation(payload, command)

    return None


def post_tool_use_violation(payload: dict[str, Any]) -> str | None:
    if not is_edit_tool(str(payload.get("tool_name") or "")):
        return None

    touched = edit_paths(payload, tool_command(payload))
    sensitive = [path for path in touched if is_sensitive_secret_path(path)]
    if not sensitive:
        return None

    root = repo_root(payload)
    for rel_path in sensitive:
        path = safe_join(root, rel_path)
        if not path or not path.is_file():
            continue
        text = read_limited(path)
        hit = first_secret_hit(text, SENSITIVE_FILE_PATTERNS)
        if hit:
            return f"Secret scan blocked sensitive edit: {rel_path} contains {hit}."
    return None


def bash_violation(payload: dict[str, Any], command: str) -> str | None:
    if git_push_force(command):
        return "Blocked by Hermes policy: git push --force / -f is forbidden."

    if git_reset_hard(command):
        return "Blocked by Hermes policy: git reset --hard requires explicit АЮ confirmation before running."

    rm_target = dangerous_rm_target(command)
    if rm_target:
        return f"Blocked by Hermes policy: rm -rf against {rm_target} is forbidden."

    if git_commit(command):
        hit = staged_secret_hit(payload)
        if hit:
            return f"Blocked by Hermes pre-commit secret scan: staged diff contains {hit}."

    return None


def edit_violation(payload: dict[str, Any], command: str) -> str | None:
    paths = edit_paths(payload, command)
    if not paths:
        return None

    for rel_path in paths:
        norm = normalize_rel_path(rel_path)
        if norm == "ROADMAP.md" and not roadmap_keeper_context(payload):
            return "Blocked by Hermes policy: edit ROADMAP.md only via skill hermes-main-roadmap-keeper."

        if is_production_lock_path(norm) and not hermes_lock_context(payload):
            return "Blocked by Hermes policy: production lock files may be edited only by hermes-lock-* skills."

        if norm.startswith("sync/"):
            return "Blocked by Hermes policy: sync/* handoff files are protected from direct Edit/Write."

        domain_reason = role_domain_violation(norm)
        if domain_reason:
            return domain_reason

    secret_reason = pre_edit_secret_violation(payload, paths, command)
    if secret_reason:
        return secret_reason

    return None


def temp_block_violation(payload: dict[str, Any], command: str) -> str | None:
    root = repo_root(payload)
    blocklist = root / TEMP_BLOCKLIST
    if not blocklist.is_file():
        return None
    for line in blocklist.read_text(encoding="utf-8").splitlines():
        pattern = line.strip()
        if pattern and not pattern.startswith("#") and pattern in command:
            return f"Blocked by temporary Hermes hook test pattern: {pattern}"
    return None


def git_push_force(command: str) -> bool:
    for segment in shell_segments(command):
        tokens = shell_tokens(segment)
        if len(tokens) >= 3 and tokens[0] == "git" and tokens[1] == "push":
            if any(token in {"--force", "-f"} or token.startswith("--force-with-lease") for token in tokens[2:]):
                return True
    return False


def git_reset_hard(command: str) -> bool:
    for segment in shell_segments(command):
        tokens = shell_tokens(segment)
        if len(tokens) >= 3 and tokens[0] == "git" and tokens[1] == "reset" and "--hard" in tokens[2:]:
            return True
    return False


def git_commit(command: str) -> bool:
    for segment in shell_segments(command):
        tokens = shell_tokens(segment)
        if len(tokens) >= 2 and tokens[0] == "git" and tokens[1] == "commit":
            return True
    return False


def dangerous_rm_target(command: str) -> str | None:
    for segment in shell_segments(command):
        tokens = shell_tokens(segment)
        for i, token in enumerate(tokens):
            if token != "rm":
                continue
            flags: list[str] = []
            operands: list[str] = []
            for arg in tokens[i + 1 :]:
                if arg == "--":
                    continue
                if arg.startswith("-") and not operands:
                    flags.append(arg)
                    continue
                operands.append(strip_quotes(arg))
            if not has_recursive_force(flags):
                continue
            for operand in operands:
                target = dangerous_root_match(operand)
                if target:
                    return target
    return regex_dangerous_rm(command)


def has_recursive_force(flags: list[str]) -> bool:
    joined = "".join(flags)
    return "r" in joined and "f" in joined


def dangerous_root_match(raw: str) -> str | None:
    value = raw.rstrip("/")
    if raw == "/":
        return "/"
    for root in DANGEROUS_RM_ROOTS[1:]:
        if value == root or value.startswith(root + "/"):
            return root
    return None


def regex_dangerous_rm(command: str) -> str | None:
    compact = re.sub(r"\s+", " ", command)
    if re.search(r"\brm\s+-[A-Za-z]*r[A-Za-z]*f[A-Za-z]*\s+['\"]?/['\"]?(?:\s|$)", compact):
        return "/"
    for root in DANGEROUS_RM_ROOTS[1:]:
        if re.search(r"\brm\s+-[A-Za-z]*r[A-Za-z]*f[A-Za-z]*\s+['\"]?" + re.escape(root), compact):
            return root
    return None


def patch_paths(command: str) -> list[str]:
    paths: list[str] = []
    patterns = (
        r"^\*\*\* (?:Add|Update|Delete) File: (.+)$",
        r"^\*\*\* Move to: (.+)$",
        r"^\+\+\+ b/(.+)$",
        r"^--- a/(.+)$",
    )
    for line in command.splitlines():
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                paths.append(normalize_rel_path(match.group(1).strip()))
    return sorted(set(path for path in paths if path and path != "/dev/null"))


def edit_paths(payload: dict[str, Any], command: str) -> list[str]:
    paths = set(patch_paths(command))
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("file_path", "path", "filename"):
            value = tool_input.get(key)
            if isinstance(value, str):
                paths.add(normalize_rel_path(value))
    return sorted(path for path in paths if path and path != "/dev/null")


def is_edit_tool(tool_name: str) -> bool:
    return tool_name in {"Edit", "Write", "apply_patch"}


def pre_edit_secret_violation(payload: dict[str, Any], paths: list[str], command: str) -> str | None:
    if not any(is_sensitive_secret_path(path) for path in paths):
        return None
    hit = first_secret_hit(command + "\n" + tool_input_text(payload), SENSITIVE_FILE_PATTERNS)
    if hit:
        return f"Blocked by Hermes secret scan: sensitive file edit contains {hit}."
    return None


def staged_secret_hit(payload: dict[str, Any]) -> str | None:
    root = repo_root(payload)
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--"],
            cwd=root,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except Exception:
        return None
    return first_secret_hit(result.stdout, API_KEY_PATTERNS)


def first_secret_hit(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> str | None:
    for label, pattern in patterns:
        if pattern.search(text):
            return label
    return None


def is_sensitive_secret_path(path: str) -> bool:
    name = Path(path).name
    return name.startswith(".env") or name.endswith(".env") or name.endswith(".pem") or name.endswith(".key")


def is_production_lock_path(path: str) -> bool:
    return (
        path == "/root/.hermes/codex_locks/production.json"
        or path.endswith("/root/.hermes/codex_locks/production.json")
        or path == "production.json"
        or "codex_locks/production.json" in path
    )


def role_domain_violation(path: str) -> str | None:
    role = os.environ.get("HERMES_AGENT_ROLE", "").strip().lower()
    if not role:
        return None

    allowed: dict[str, tuple[str, ...]] = {
        "hermes-main": ("AGENTS.md", "ROADMAP.md", ".codex/", ".github/", ".agents/", "docs/"),
        "hermes-pm": ("docs/", "issues/", "specs/"),
        "hermes-research": ("docs/", "research/"),
        "hermes-dev-core": ("agent/", "hermes_cli/", "src/", "tests/", "scripts/", "pyproject.toml", "uv.lock"),
        "hermes-dev-edge": ("gateway/", "plugins/", "web/", "tests/", "scripts/", "pyproject.toml", "uv.lock"),
        "hermes-qa": ("tests/", "scripts/", "docs/"),
    }
    prefixes = allowed.get(role)
    if not prefixes:
        return None
    if not any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in prefixes):
        return f"Blocked by Hermes Domain Guard: role {role} cannot edit {path}."
    return None


def roadmap_keeper_context(payload: dict[str, Any]) -> bool:
    return "hermes-main-roadmap-keeper" in explicit_context_values(payload)


def hermes_lock_context(payload: dict[str, Any]) -> bool:
    return any(re.fullmatch(r"hermes-lock-[a-z0-9-]+", value) for value in explicit_context_values(payload))


def explicit_context_values(payload: dict[str, Any]) -> set[str]:
    values = {
        os.environ.get("HERMES_ACTIVE_SKILL", ""),
        os.environ.get("CODEX_ACTIVE_SKILL", ""),
        os.environ.get("CODEX_SKILL", ""),
        str(payload.get("active_skill") or ""),
    }
    return {value.strip().lower() for value in values if value.strip()}


def shell_segments(command: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"\s*(?:&&|\|\||;|\n)\s*", command) if segment.strip()]


def shell_tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def strip_quotes(value: str) -> str:
    return value.strip("'\"")


def normalize_rel_path(path: str) -> str:
    path = strip_quotes(path).replace("\\", "/")
    if path.startswith("b/") or path.startswith("a/"):
        path = path[2:]
    while path.startswith("./"):
        path = path[2:]
    return path


def tool_command(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, dict):
        for key in ("command", "input", "patch"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return value
    return ""


def tool_input_text(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, dict):
        chunks: list[str] = []
        for key in ("command", "input", "patch", "content", "new_string", "old_string"):
            value = tool_input.get(key)
            if isinstance(value, str):
                chunks.append(value)
        return "\n".join(chunks)
    return ""


def repo_root(payload: dict[str, Any]) -> Path:
    cwd = payload.get("cwd")
    start = Path(cwd if isinstance(cwd, str) and cwd else os.getcwd())
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return Path(result.stdout.strip())
    except Exception:
        return start


def safe_join(root: Path, rel_path: str) -> Path | None:
    path = Path(rel_path)
    if path.is_absolute():
        return None
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def read_limited(path: Path, limit: int = 1_000_000) -> str:
    data = path.read_bytes()[:limit]
    return data.decode("utf-8", errors="ignore")


if __name__ == "__main__":
    raise SystemExit(main())
