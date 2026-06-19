#!/usr/bin/env python3
"""Small GitHub REST helpers for Hermes CI gates."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


API_VERSION = "2022-11-28"
API_ROOT = "https://api.github.com"


def api_request(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "hermes-ci-gates",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(f"{API_ROOT}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} failed: HTTP {exc.code}: {detail}") from exc
    if not body:
        return None
    return json.loads(body)


def split_repo(repo: str) -> tuple[str, str]:
    owner, name = repo.split("/", 1)
    return owner, name


def repo_from_env() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo or "/" not in repo:
        raise RuntimeError("GITHUB_REPOSITORY is not set to owner/repo.")
    return repo


def post_or_update_comment(repo: str, issue_number: int, token: str, marker: str, body: str) -> None:
    if not token:
        print("::warning::GITHUB_TOKEN is empty; cannot post validation comment.")
        return

    comments = api_request("GET", f"/repos/{repo}/issues/{issue_number}/comments?per_page=100", token)
    existing = next((comment for comment in comments if marker in str(comment.get("body", ""))), None)
    full_body = f"{marker}\n{body}"
    if existing:
        api_request("PATCH", f"/repos/{repo}/issues/comments/{existing['id']}", token, {"body": full_body})
    else:
        api_request("POST", f"/repos/{repo}/issues/{issue_number}/comments", token, {"body": full_body})


def fetch_issue(repo: str, issue_number: int, token: str) -> dict[str, Any]:
    return api_request("GET", f"/repos/{repo}/issues/{issue_number}", token)


def fetch_pull_request(repo: str, pr_number: int, token: str) -> dict[str, Any]:
    return api_request("GET", f"/repos/{repo}/pulls/{pr_number}", token)
