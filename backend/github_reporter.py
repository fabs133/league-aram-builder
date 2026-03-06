"""
ARAM Oracle — GitHub Issue Reporter

Posts bug reports as GitHub issues. Token and repo loaded from config.toml:
  [github]
  github_token = "ghp_..."
  github_repo = "owner/repo"
"""

import logging

import requests

from backend.config import config

logger = logging.getLogger("aram-oracle.github")

API_BASE = "https://api.github.com"
MAX_BODY_LENGTH = 60_000  # GitHub limit ~65K, leave margin


def _get_token() -> str | None:
    token = config.get("github_token", "")
    return token if token else None


def _get_repo() -> str | None:
    repo = config.get("github_repo", "")
    return repo if repo else None


def post_issue(
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> dict | None:
    """Create a GitHub issue. Returns API response dict or None on failure."""
    token = _get_token()
    if not token:
        logger.warning("No github_token configured — skipping issue creation")
        return None

    repo = _get_repo()
    if not repo:
        logger.warning("No github_repo configured — skipping issue creation")
        return None

    if len(body) > MAX_BODY_LENGTH:
        body = body[:MAX_BODY_LENGTH] + "\n\n---\n*Report truncated (exceeded size limit)*"

    url = f"{API_BASE}/repos/{repo}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "title": title,
        "body": body,
        "labels": labels or ["bug", "auto-report"],
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code == 201:
            data = resp.json()
            logger.info("GitHub issue created: %s", data.get("html_url"))
            return data
        else:
            logger.error("GitHub API error %d: %s", resp.status_code, resp.text[:200])
            return None
    except Exception as e:
        logger.error("Failed to post GitHub issue: %s", e)
        return None
