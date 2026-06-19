#!/usr/bin/env python3
"""Validate Hermes issue/PR label invariants and comment on failures."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from hermes_github_api import fetch_issue, post_or_update_comment, repo_from_env


MARKER = "<!-- hermes-label-validator -->"
REQUIRED_EXACTLY_ONE = ("lane", "type", "status")
OPTIONAL_AT_MOST_ONE = ("risk",)


def main() -> int:
    args = parse_args()
    payload = read_json(Path(args.event_file))
    event_name = args.event_name or os.environ.get("GITHUB_EVENT_NAME", "")
    repo = args.repo or repo_from_env()
    token = args.token or os.environ.get("GITHUB_TOKEN", "")

    target = resolve_target(payload, event_name, repo, token, args.target_number)
    labels = sorted(label_name(label) for label in target["labels"])
    labels = [label for label in labels if label]
    violations = validate_labels(labels)

    if not violations:
        body = success_comment(target["kind"], target["number"], labels)
        print(body)
        write_step_summary(body)
        if args.post_comment:
            post_or_update_comment(repo, target["number"], token, MARKER, body)
        return 0

    body = failure_comment(target["kind"], target["number"], labels, violations)
    print(body)
    write_step_summary(body)
    if args.post_comment:
        post_or_update_comment(repo, target["number"], token, MARKER, body)
    print(f"::error title=Hermes label invariant failure::#{target['number']} has invalid labels.")
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-file", default=os.environ.get("GITHUB_EVENT_PATH", ""))
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--target-number", type=int, default=target_number_from_env())
    parser.add_argument(
        "--post-comment",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("HERMES_POST_COMMENT", "true").lower() != "false",
    )
    return parser.parse_args()


def target_number_from_env() -> int | None:
    value = os.environ.get("HERMES_TARGET_NUMBER") or ""
    return int(value) if value.isdigit() else None


def read_json(path: Path) -> dict[str, Any]:
    if not path:
        raise SystemExit("GITHUB_EVENT_PATH is required.")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_target(
    payload: dict[str, Any],
    event_name: str,
    repo: str,
    token: str,
    explicit_number: int | None,
) -> dict[str, Any]:
    if event_name == "pull_request":
        pr = payload["pull_request"]
        return {"kind": "PR", "number": int(pr["number"]), "labels": pr.get("labels", [])}

    if event_name == "issues":
        issue = payload["issue"]
        return {"kind": "issue", "number": int(issue["number"]), "labels": issue.get("labels", [])}

    if event_name == "workflow_dispatch":
        inputs = payload.get("inputs", {})
        number = explicit_number or int(inputs.get("target_number") or 0)
        if number <= 0:
            raise SystemExit("workflow_dispatch requires target_number.")
        issue = fetch_issue(repo, number, token)
        kind = "PR" if issue.get("pull_request") else "issue"
        return {"kind": kind, "number": number, "labels": issue.get("labels", [])}

    raise SystemExit(f"Unsupported event for label validation: {event_name}")


def label_name(label: Any) -> str:
    if isinstance(label, str):
        return label
    if isinstance(label, dict):
        return str(label.get("name") or "")
    return ""


def validate_labels(labels: list[str]) -> list[str]:
    violations: list[str] = []
    grouped = {prefix: [label for label in labels if label.startswith(f"{prefix}:")] for prefix in all_prefixes()}

    for prefix in REQUIRED_EXACTLY_ONE:
        count = len(grouped[prefix])
        if count != 1:
            violations.append(f"expected exactly one `{prefix}:*` label, found {count}: {display(grouped[prefix])}")

    for prefix in OPTIONAL_AT_MOST_ONE:
        count = len(grouped[prefix])
        if count > 1:
            violations.append(f"expected at most one `{prefix}:*` label, found {count}: {display(grouped[prefix])}")

    return violations


def all_prefixes() -> tuple[str, ...]:
    return REQUIRED_EXACTLY_ONE + OPTIONAL_AT_MOST_ONE


def display(labels: list[str]) -> str:
    return ", ".join(f"`{label}`" for label in labels) if labels else "none"


def failure_comment(kind: str, number: int, labels: list[str], violations: list[str]) -> str:
    lines = [
        "## Hermes Label Validator failed",
        "",
        f"{kind} `#{number}` does not satisfy the Hermes orchestration label rules.",
        "",
        "Required:",
        "- exactly one `lane:*` label",
        "- exactly one `type:*` label",
        "- exactly one `status:*` label",
        "- at most one `risk:*` label",
        "",
        "Current labels:",
        display(labels),
        "",
        "Violations:",
    ]
    lines.extend(f"- {violation}" for violation in violations)
    return "\n".join(lines)


def success_comment(kind: str, number: int, labels: list[str]) -> str:
    return "\n".join(
        [
            "## Hermes Label Validator passed",
            "",
            f"{kind} `#{number}` satisfies the Hermes orchestration label rules.",
            "",
            "Current labels:",
            display(labels),
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
