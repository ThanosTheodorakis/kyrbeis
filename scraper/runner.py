"""Run Kyrbeis inside Docker: keep a clone of the GitHub repository and collect every day.

    python -m scraper.runner serve   # stay running; collect daily at RUN_AT (the container's default)
    python -m scraper.runner once    # collect once now and exit

Settings come from environment variables (docker-compose.yml reads them from .env):

    REPO_URL        https address of your GitHub repository, e.g. https://github.com/you/kyrbeis
    GITHUB_TOKEN    a fine-grained token with "Contents: read and write" on that repository only
    RUN_AT          daily time in Athens time, HH:MM (default 06:17)
    KYRBEIS_CONTACT optional contact for site owners (default: the repository's issues page)
    KYRBEIS_REPO_DIR where the clone lives (default /repo, a Docker volume)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scraper import update as up

TZ = ZoneInfo("Europe/Athens")
STATE_FILE = "kyrbeis-last-success"  # kept inside .git/, so it is never committed
RETRY_AFTER = 3600  # after a failed run (e.g. no internet), try again in an hour
log = logging.getLogger("kyrbeis.runner")


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


def parse_run_at(text: str) -> tuple[int, int]:
    try:
        hh, mm = (int(x) for x in text.strip().split(":"))
        if 0 <= hh < 24 and 0 <= mm < 60:
            return hh, mm
    except ValueError:
        pass
    raise ConfigError(f"RUN_AT must look like 06:17, not {text!r}")


def todays_run(now: datetime, run_at: tuple[int, int]) -> datetime:
    return now.replace(hour=run_at[0], minute=run_at[1], second=0, microsecond=0)


def is_due(now: datetime, run_at: tuple[int, int], last_success: date | None) -> bool:
    """Due once today's run time has passed and today hasn't succeeded yet.
    So a machine that was off at RUN_AT collects as soon as it starts."""
    return now >= todays_run(now, run_at) and last_success != now.date()


def seconds_until_next(now: datetime, run_at: tuple[int, int]) -> float:
    nxt = todays_run(now, run_at)
    if nxt <= now:
        nxt = todays_run(now + timedelta(days=1), run_at)
    return (nxt - now).total_seconds()


def read_last_success(repo: Path) -> date | None:
    f = repo / ".git" / STATE_FILE
    try:
        return date.fromisoformat(f.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_last_success(repo: Path, day: date) -> None:
    (repo / ".git" / STATE_FILE).write_text(day.isoformat(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


def settings() -> dict:
    repo_url = os.environ.get("REPO_URL", "").strip()
    if not repo_url.startswith(("https://", "file://", "/")):
        raise ConfigError("set REPO_URL to your repository's https address, e.g. https://github.com/you/kyrbeis")
    if repo_url.startswith("https://") and not os.environ.get("GITHUB_TOKEN"):
        raise ConfigError("set GITHUB_TOKEN so the container can push (see the README)")
    return {
        "repo_url": repo_url,
        "repo_dir": Path(os.environ.get("KYRBEIS_REPO_DIR", "/repo")),
        "run_at": parse_run_at(os.environ.get("RUN_AT", "06:17")),
    }


def ensure_clone(repo_url: str, repo_dir: Path) -> None:
    """Clone the repository on first start; afterwards update.update() pulls."""
    if (repo_dir / ".git").exists():
        return
    repo_dir.mkdir(parents=True, exist_ok=True)
    if any(repo_dir.iterdir()):
        raise ConfigError(f"{repo_dir} is not empty and not a git repository")
    log.info("first start: cloning %s", repo_url)
    up.git(repo_dir, "clone", "--quiet", repo_url, ".")


def collect(cfg: dict, day: date | None = None, **update_kw) -> int:
    """One collection. On success, record `day` (the day the run was due for) as done."""
    ensure_clone(cfg["repo_url"], cfg["repo_dir"])
    rc = up.update(cfg["repo_dir"], **update_kw)
    if rc == 0:
        write_last_success(cfg["repo_dir"], day or datetime.now(TZ).date())
    return rc


def serve(
    cfg: dict, clock=lambda: datetime.now(TZ), sleep=time.sleep, max_loops: int | None = None, **update_kw
) -> None:
    loops = 0
    log.info("running; collecting every day at %02d:%02d Athens time", *cfg["run_at"])
    while max_loops is None or loops < max_loops:
        loops += 1
        now = clock()
        repo = cfg["repo_dir"]
        last = read_last_success(repo) if (repo / ".git").exists() else None
        if is_due(now, cfg["run_at"], last):
            try:
                ok = collect(cfg, day=now.date(), **update_kw) == 0
            except ConfigError:
                raise
            except Exception as e:  # noqa: BLE001 - e.g. no internet for the first clone: retry, don't crash-loop
                log.error("collection crashed: %s", e)
                ok = False
            if ok:
                continue  # recompute the wait from the new state
            log.warning("collection failed; trying again in %d minutes", RETRY_AFTER // 60)
            sleep(RETRY_AFTER)
            continue
        wait = seconds_until_next(now, cfg["run_at"])
        log.info("next collection in %.1f hours", wait / 3600)
        sleep(wait)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["serve", "once"], nargs="?", default="serve")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M")
    try:
        cfg = settings()
        if a.command == "once":
            return collect(cfg)
        serve(cfg)
        return 0
    except ConfigError as e:
        log.error("%s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
