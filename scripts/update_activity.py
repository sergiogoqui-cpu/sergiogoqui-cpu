#!/usr/bin/env python3
"""Rewrite the RECENT_ACTIVITY block in README.md from public GitHub events.

Self-hosted on purpose: earlier versions of this profile used a
third-party stats widget (github-readme-streak-stats) that turned out to
be unreliable in practice (see repo history). Everything here runs on
GitHub's own infrastructure with GITHUB_TOKEN — no external service to
go down.

Only public events are visible via this API (GitHub does not expose
private-repo event details to unauthenticated/user-scoped event
listings), which is the right scope for a public profile anyway: this
surfaces real activity on the public repos without needing any special
handling to keep private work private.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USERNAME = "sergiogoqui-cpu"
EVENTS_URL = f"https://api.github.com/users/{USERNAME}/events/public"
README_PATH = Path(__file__).resolve().parent.parent / "README.md"
START_MARKER = "<!--RECENT_ACTIVITY:START-->"
END_MARKER = "<!--RECENT_ACTIVITY:END-->"
MAX_ITEMS = 6

# Event types worth surfacing, and how to render one. Noisy/low-signal
# types (WatchEvent, ForkEvent, most IssueCommentEvent) are omitted on
# purpose - the goal is "what did they build," not everything logged.
def format_push(event: dict) -> str | None:
    repo = event["repo"]["name"]
    commits = event.get("payload", {}).get("commits", [])
    if not commits:
        return None
    n = len(commits)
    noun = "commit" if n == 1 else "commits"
    return f"Pushed {n} {noun} to [{repo}](https://github.com/{repo})"


def format_issue(event: dict) -> str | None:
    action = event.get("payload", {}).get("action")
    if action != "opened":
        return None
    repo = event["repo"]["name"]
    issue = event["payload"]["issue"]
    return f"Opened [#{issue['number']}]({issue['html_url']}) in [{repo}](https://github.com/{repo}): {issue['title']}"


def format_pr(event: dict) -> str | None:
    action = event.get("payload", {}).get("action")
    if action not in ("opened", "merged"):
        return None
    repo = event["repo"]["name"]
    pr = event["payload"]["pull_request"]
    verb = "Merged" if pr.get("merged") else "Opened"
    return f"{verb} PR [#{pr['number']}]({pr['html_url']}) in [{repo}](https://github.com/{repo}): {pr['title']}"


def format_release(event: dict) -> str | None:
    if event.get("payload", {}).get("action") != "published":
        return None
    repo = event["repo"]["name"]
    release = event["payload"]["release"]
    tag = release.get("tag_name", "")
    return f"Released [{tag}]({release['html_url']}) of [{repo}](https://github.com/{repo})"


def format_create(event: dict) -> str | None:
    if event.get("payload", {}).get("ref_type") != "repository":
        return None
    repo = event["repo"]["name"]
    return f"Created [{repo}](https://github.com/{repo})"


FORMATTERS = {
    "PushEvent": format_push,
    "IssuesEvent": format_issue,
    "PullRequestEvent": format_pr,
    "ReleaseEvent": format_release,
    "CreateEvent": format_create,
}


def relative_date(iso_ts: str) -> str:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    days = (datetime.now(timezone.utc) - dt).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days}d ago"
    weeks = days // 7
    return f"{weeks}w ago"


def fetch_events() -> list[dict]:
    req = urllib.request.Request(EVENTS_URL, headers={"User-Agent": USERNAME, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_activity_lines(events: list[dict]) -> list[str]:
    lines: list[str] = []
    seen_push_repo_day: set[tuple[str, str]] = set()

    for event in events:
        formatter = FORMATTERS.get(event["type"])
        if formatter is None:
            continue

        # Collapse multiple same-day pushes to the same repo into one line
        # instead of listing every push individually.
        if event["type"] == "PushEvent":
            day = event["created_at"][:10]
            key = (event["repo"]["name"], day)
            if key in seen_push_repo_day:
                continue
            seen_push_repo_day.add(key)

        text = formatter(event)
        if text is None:
            continue

        lines.append(f"- {text} — _{relative_date(event['created_at'])}_")
        if len(lines) >= MAX_ITEMS:
            break

    return lines


def render_block(lines: list[str]) -> str:
    if not lines:
        return "_No public activity yet — check back soon._"
    return "\n".join(lines)


def update_readme(block: str) -> bool:
    text = README_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL
    )
    replacement = f"{START_MARKER}\n{block}\n{END_MARKER}"
    if not pattern.search(text):
        print("ERROR: markers not found in README.md", file=sys.stderr)
        sys.exit(1)

    new_text = pattern.sub(replacement, text, count=1)
    if new_text == text:
        return False

    README_PATH.write_text(new_text, encoding="utf-8")
    return True


def main() -> None:
    events = fetch_events()
    lines = build_activity_lines(events)
    block = render_block(lines)
    changed = update_readme(block)
    print("README.md updated" if changed else "No change")


if __name__ == "__main__":
    main()
