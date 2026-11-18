#!/usr/bin/env python3

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Monitor OpenJDK branches for the Java4Shell Base64 decoder fix."""

from __future__ import annotations

import argparse
import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

TARGET_TERMS = ("8393212", "CVE-2026-114938")
SOURCES = (
    ("openjdk/jdk21u", "master"),
    ("openjdk/jdk21u", "jdk21.0.13.1"),
    ("openjdk/jdk", "master"),
)
SOURCE_PATH = "src/hotspot/cpu/x86/stubGenerator_x86_64.cpp"
DEFAULT_INTERVAL = 600
DEFAULT_STATE_FILE = (
    Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()
    / "jenkins-k8s-operator/openjdk-cve-2026-114938.json"
)
ATOM_NS = "{http://www.w3.org/2005/Atom}"


def fetch_commits(repository: str, branch: str) -> list[dict[str, str]]:
    """Return recent commits touching the OpenJDK Base64 decoder."""
    url = f"https://github.com/{repository}/commits/{quote(branch, safe='')}/{SOURCE_PATH}.atom"
    request = Request(  # noqa: S310 - URL is constructed from fixed GitHub components
        url, headers={"User-Agent": "jenkins-k8s-cve-monitor"}
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS GitHub URL
        root = ET.parse(response).getroot()  # noqa: S314 - GitHub's fixed Atom response
    commits = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        link = entry.find(f"{ATOM_NS}link[@rel='alternate']")
        commit_url = link.get("href", "") if link is not None else ""
        commits.append(
            {
                "sha": (entry.findtext(f"{ATOM_NS}id") or "").rsplit("/", 1)[-1],
                "message": (entry.findtext(f"{ATOM_NS}title") or "").strip(),
                "url": commit_url,
            }
        )
    return commits


def matching_commits() -> list[dict[str, str]]:
    """Find commits whose subject identifies the security fix."""
    matches: dict[str, dict[str, str]] = {}
    for repository, branch in SOURCES:
        for commit in fetch_commits(repository, branch):
            if not any(term.lower() in commit["message"].lower() for term in TARGET_TERMS):
                continue
            item = matches.setdefault(
                commit["sha"],
                {
                    "repository": repository,
                    "branch": branch,
                    "sha": commit["sha"],
                    "message": commit["message"],
                    "url": commit["url"],
                },
            )
            item["branch"] += f", {branch}" if branch not in item["branch"] else ""
    return list(matches.values())


def load_seen(path: Path) -> set[str]:
    """Read previously reported commit SHAs."""
    try:
        return set(json.loads(path.read_text()))
    except FileNotFoundError:
        return set()


def save_seen(path: Path, seen: set[str]) -> None:
    """Persist reported commit SHAs atomically enough for this single-process monitor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(seen), indent=2) + "\n")


def check_once(state_file: Path) -> bool:
    """Check once, print new findings, and return whether a fix is present."""
    matches = matching_commits()
    seen = load_seen(state_file)
    for match in matches:
        if match["sha"] not in seen:
            print(
                f"PATCH LANDED: {match['repository']}:{match['branch']} "
                f"{match['sha'][:12]} {match['message']} {match['url']}",
                flush=True,
            )
    save_seen(state_file, seen | {match["sha"] for match in matches})
    if not matches:
        print("No matching OpenJDK patch found.", flush=True)
    return bool(matches)


def main() -> None:
    """Poll until the upstream patch is visible."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL, help="Seconds between checks."
    )
    parser.add_argument(
        "--once", action="store_true", help="Check once instead of polling forever."
    )
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")

    while True:
        check_once(args.state_file)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
