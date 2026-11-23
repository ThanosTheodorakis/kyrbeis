"""Daily collection from your own computer (Windows, macOS or Linux).

Gets the latest code from GitHub, runs the scraper, then commits and pushes the new
data. The push makes GitHub republish the site. Schedule it to run every morning
(see "Collect the data on your computer" in the README).

    python -m scraper.update             # what the scheduled task runs
    python -m scraper.update --no-push   # try it: scrape and commit, but don't push

Your site address and contact link are worked out from the repository's GitHub
address. Set KYRBEIS_CONTACT to use a different contact (a URL or an e-mail).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
LOCK_NAME = ".update.lock"
STALE_LOCK_SECONDS = 2 * 3600  # a lock older than this was left by a crashed run
log = logging.getLogger("kyrbeis.update")


class AlreadyRunning(Exception):
    pass


class Lock:
    """Stop two runs at once (a slow run overlapping the next scheduled one).
    A lock file works the same on every OS."""

    def __init__(self, root: Path):
        self.path = root / LOCK_NAME

    def __enter__(self) -> Lock:
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                age = time.time() - self.path.stat().st_mtime
                if age < STALE_LOCK_SECONDS:
                    raise AlreadyRunning(f"another update started {int(age)} s ago is still running") from None
                log.warning("removing a lock left by a crashed run (%d min old)", age // 60)
                self.path.unlink(missing_ok=True)
        raise AlreadyRunning("could not take the lock")

    def __exit__(self, *exc) -> None:
        self.path.unlink(missing_ok=True)


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=check, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def github_addresses(remote_url: str) -> tuple[str, str]:
    """GitHub remote -> (site URL, issues URL). Works for https and ssh remotes."""
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", remote_url.strip())
    if not m:
        return "", ""
    owner, repo = m.groups()
    return f"https://{owner.lower()}.github.io/{repo}/", f"https://github.com/{owner}/{repo}/issues"


def run_scraper(root: Path, site_url: str, contact: str) -> int:
    """Run the scraper as a separate process, so it uses the code just pulled."""
    cmd = [sys.executable, "-m", "scraper.gov_scraper", "--site-data", "data", "--site-url", site_url]
    if contact:
        cmd += ["--contact", contact]
    return subprocess.run(cmd, cwd=root, check=False).returncode


def update(
    root: Path = ROOT,
    scrape: Callable[[Path, str, str], int] = run_scraper,
    push: bool = True,
    retry_delay: float = 10,
) -> int:
    """One collection run. Returns 0 on success (or nothing to do), 1 on failure."""
    if git(root, "rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        log.error("%s is not a git repository: put the project on GitHub and clone it first (see the README)", root)
        return 1
    try:
        lock = Lock(root).__enter__()
    except AlreadyRunning as e:
        log.info("skipping: %s", e)
        return 0
    try:
        remote = git(root, "remote", "get-url", "origin", check=False).stdout.strip()
        if remote:
            pulled = git(root, "pull", "--rebase", "--autostash", "--quiet", check=False)
            if pulled.returncode:
                log.warning("could not get the latest version from GitHub: %s", pulled.stderr.strip())
        else:
            log.warning("no GitHub remote set up: the data will only be committed locally")
        site_url, issues_url = github_addresses(remote)
        contact = os.environ.get("KYRBEIS_CONTACT") or issues_url

        if scrape(root, site_url, contact) != 0:
            log.error("the scraper failed (no source answered?): nothing committed, the old data stays")
            return 1

        git(root, "add", "data")
        if git(root, "diff", "--cached", "--quiet", check=False).returncode == 0:
            log.info("no changes")
            return 0
        day = datetime.now(ZoneInfo("Europe/Athens")).strftime("%Y-%m-%d")
        git(root, "commit", "--quiet", "-m", f"data: update {day}")
        log.info("committed the new data")
        if not push or not remote:
            return 0

        for attempt in range(1, 4):
            pushed = git(root, "push", "--quiet", check=False)
            if pushed.returncode == 0:
                log.info("pushed: GitHub will republish the site in a minute or two")
                return 0
            log.warning("push failed (attempt %d): %s", attempt, pushed.stderr.strip())
            time.sleep(retry_delay * attempt)
            git(root, "pull", "--rebase", "--quiet", check=False)  # someone else pushed meanwhile
        log.error("could not push: the data is committed locally and goes out with the next run")
        return 1
    finally:
        lock.__exit__(None, None, None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-push", action="store_true", help="commit the new data but don't push it")
    ap.add_argument("--log-file", default=str(ROOT / "update.log"), help="also append the output here")
    a = ap.parse_args(argv)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if a.log_file:
        handlers.append(logging.FileHandler(a.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M", handlers=handlers
    )
    return update(push=not a.no_push)


if __name__ == "__main__":
    sys.exit(main())
