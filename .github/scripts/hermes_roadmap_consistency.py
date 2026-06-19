#!/usr/bin/env python3
"""Validate ROADMAP.md changes in pull requests."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from hermes_github_api import fetch_pull_request, post_or_update_comment, repo_from_env


MARKER = "<!-- hermes-roadmap-consistency -->"
ROADMAP_COMMIT_RE = re.compile(r"^chore\(roadmap\): .+")


def main() -> int:
    args = parse_args()
    payload = read_json(Path(args.event_file))
    event_name = args.event_name or os.environ.get("GITHUB_EVENT_NAME", "")
    repo = args.repo or repo_from_env()
    token = args.token or os.environ.get("GITHUB_TOKEN", "")

    pr = resolve_pr(payload, event_name, repo, token, args.pr_number)
    base_sha = pr["base_sha"]
    head_sha = pr["head_sha"]

    if not roadmap_changed(base_sha, head_sha):
        body = success_comment(pr["number"], "ROADMAP.md is unchanged in this PR.")
        print(body)
        write_step_summary(body)
        if args.post_comment:
            post_or_update_comment(repo, pr["number"], token, MARKER, body)
        return 0

    commits = roadmap_commits(base_sha, head_sha)
    bad_commits = [(sha, subject) for sha, subject in commits if not ROADMAP_COMMIT_RE.match(subject)]
    if not bad_commits:
        body = success_comment(
            pr["number"],
            "ROADMAP.md changes use keeper-style `chore(roadmap): ...` commits.",
        )
        print(body)
        write_step_summary(body)
        if args.post_comment:
            post_or_update_comment(repo, pr["number"], token, MARKER, body)
        return 0

    body = failure_comment(pr["number"], bad_commits)
    print(body)
    write_step_summary(body)
    if args.post_comment:
        post_or_update_comment(repo, pr["number"], token, MARKER, body)
    print(f"::error title=Hermes ROADMAP consistency failure::PR #{pr['number']} has manual ROADMAP.md edits.")
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-file", default=os.environ.get("GITHUB_EVENT_PATH", ""))
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--pr-number", type=int, default=pr_number_from_env())
    parser.add_argument(
        "--post-comment",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("HERMES_POST_COMMENT", "true").lower() != "false",
    )
    return parser.parse_args()


def pr_number_from_env() -> int | None:
    value = os.environ.get("HERMES_PR_NUMBER") or ""
    return int(value) if value.isdigit() else None


def read_json(path: Path) -> dict[str, Any]:
    if not path:
        raise SystemExit("GITHUB_EVENT_PATH is required.")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_pr(
    payload: dict[str, Any],
    event_name: str,
    repo: str,
    token: str,
    explicit_number: int | None,
) -> dict[str, Any]:
    if event_name == "pull_request":
        pr = payload["pull_request"]
        return {
            "number": int(pr["number"]),
            "base_sha": pr["base"]["sha"],
            "head_sha": pr["head"]["sha"],
        }

    if event_name == "workflow_dispatch":
        inputs = payload.get("inputs", {})
        number = explicit_number or int(inputs.get("pr_number") or 0)
        if number <= 0:
            raise SystemExit("workflow_dispatch requires pr_number.")
        pr = fetch_pull_request(repo, number, token)
        return {
            "number": number,
            "base_sha": pr["base"]["sha"],
            "head_sha": pr["head"]["sha"],
        }

    raise SystemExit(f"Unsupported event for roadmap validation: {event_name}")


def roadmap_changed(base_sha: str, head_sha: str) -> bool:
    result = run_git(["diff", "--quiet", f"{base_sha}...{head_sha}", "--", "ROADMAP.md"], check=False)
    return result.returncode == 1


def roadmap_commits(base_sha: str, head_sha: str) -> list[tuple[str, str]]:
    result = run_git(["log", "--format=%H%x01%s", f"{base_sha}..{head_sha}", "--", "ROADMAP.md"])
    commits: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if "\x01" not in line:
            continue
        sha, subject = line.split("\x01", 1)
        commits.append((sha, subject))
    return commits


def run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def failure_comment(pr_number: int, bad_commits: list[tuple[str, str]]) -> str:
    lines = [
        "## Hermes Roadmap Consistency failed",
        "",
        f"PR `#{pr_number}` changes `ROADMAP.md`, but at least one ROADMAP commit does not look keeper-generated.",
        "",
        "Required commit subject for ROADMAP changes:",
        "",
        "`chore(roadmap): <short update>`",
        "",
        "Bad commits:",
    ]
    lines.extend(f"- `{sha[:7]}` `{subject}`" for sha, subject in bad_commits)
    lines.extend(
        [
            "",
            "Please revert the manual ROADMAP edit and re-apply it through `hermes-main-roadmap-keeper`.",
        ]
    )
    return "\n".join(lines)


def success_comment(pr_number: int, detail: str) -> str:
    return "\n".join(
        [
            "## Hermes Roadmap Consistency passed",
            "",
            f"PR `#{pr_number}` satisfies the Hermes ROADMAP consistency rules.",
            "",
            detail,
        ]
    )


def write_step_summary(body: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(body)
            handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
