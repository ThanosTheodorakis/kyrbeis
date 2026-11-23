"""The Docker runner (scraper/runner.py), tested without Docker: real git, a fake clock."""

import os
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

from scraper import runner as rn

TZ = rn.TZ
RUN_AT = (6, 17)


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=TZ)


# --- schedule ---------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [("06:17", (6, 17)), ("23:59", (23, 59)), (" 9:05 ", (9, 5))])
def test_parse_run_at(text, expected):
    assert rn.parse_run_at(text) == expected


@pytest.mark.parametrize("bad", ["6.17", "25:00", "06:60", "morning", ""])
def test_parse_run_at_rejects_nonsense(bad):
    with pytest.raises(rn.ConfigError):
        rn.parse_run_at(bad)


@pytest.mark.parametrize(
    "now,last,due",
    [
        (at(24, 5), None, False),  # before today's time
        (at(24, 6, 17), None, True),  # exactly on time
        (at(24, 7), date(2026, 11, 23), True),  # yesterday's done, today's due
        (at(24, 7), date(2026, 11, 24), False),  # already done today
        (at(24, 22), date(2026, 11, 20), True),  # machine was off for days: catch up when it starts
    ],
)
def test_is_due(now, last, due):
    assert rn.is_due(now, RUN_AT, last) is due


def test_seconds_until_next():
    assert rn.seconds_until_next(at(24, 6, 0), RUN_AT) == 17 * 60
    assert rn.seconds_until_next(at(24, 7, 17), RUN_AT) == 23 * 3600  # tomorrow


# --- repository -----------------------------------------------------------------------


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


@pytest.fixture
def github(tmp_path, monkeypatch):
    """A bare repository standing in for GitHub, with a data/ folder."""
    for k in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(k, "Kyrbeis bot")
    for k in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(k, "bot@example.com")
    remote = tmp_path / "github.git"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(remote))
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "--quiet", "--initial-branch=main")
    (seed / "data").mkdir()
    (seed / "data" / "items.json").write_text("[]\n", encoding="utf-8")
    git(seed, "add", "-A")
    git(seed, "commit", "--quiet", "-m", "init")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "--quiet", "origin", "main")
    return remote


def cfg_for(remote: Path, tmp_path: Path) -> dict:
    return {"repo_url": str(remote), "repo_dir": tmp_path / "volume", "run_at": RUN_AT}


def new_data(root, site_url, contact):
    (root / "data" / "items.json").write_text('[{"title": "Επίδομα παιδιού"}]\n', encoding="utf-8")
    return 0


def test_first_start_clones_then_collects_and_pushes(github, tmp_path):
    cfg = cfg_for(github, tmp_path)
    assert rn.collect(cfg, scrape=new_data, retry_delay=0) == 0
    assert (cfg["repo_dir"] / ".git").exists()
    assert git(github, "log", "-1", "--format=%s", "main").startswith("data: update ")
    assert rn.read_last_success(cfg["repo_dir"]) == datetime.now(TZ).date()
    # the state file lives inside .git/, so it is never committed
    assert git(cfg["repo_dir"], "status", "--porcelain") == ""


def test_a_non_empty_folder_is_not_overwritten(github, tmp_path):
    cfg = cfg_for(github, tmp_path)
    cfg["repo_dir"].mkdir()
    (cfg["repo_dir"] / "something.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(rn.ConfigError):
        rn.collect(cfg, scrape=new_data)


def test_serve_runs_once_a_day_and_catches_up(github, tmp_path):
    cfg = cfg_for(github, tmp_path)
    times = iter([at(24, 9), at(24, 9, 1)])  # machine started at 09:00, after the 06:17 time
    slept = []
    rn.serve(cfg, clock=lambda: next(times), sleep=slept.append, max_loops=2, scrape=new_data, retry_delay=0)
    assert git(github, "log", "-1", "--format=%s", "main").startswith("data: update ")  # caught up at once
    assert slept == [rn.CHECK_EVERY]  # then naps, re-checking the clock, until tomorrow


def test_serve_retries_after_a_failure(github, tmp_path):
    cfg = cfg_for(github, tmp_path)
    slept = []
    rn.serve(cfg, clock=lambda: at(24, 9), sleep=slept.append, max_loops=1, scrape=lambda *a: 1, retry_delay=0)
    assert slept == [rn.RETRY_AFTER]


def test_serve_survives_a_crash_such_as_no_internet_at_first_start(tmp_path):
    cfg = {"repo_url": str(tmp_path / "missing.git"), "repo_dir": tmp_path / "volume", "run_at": RUN_AT}
    slept = []
    rn.serve(cfg, clock=lambda: at(24, 9), sleep=slept.append, max_loops=1)
    assert slept == [rn.RETRY_AFTER]  # logged and retried later, no crash loop


# --- settings and the token helper ----------------------------------------------------


def test_settings_need_a_repo_and_a_token(monkeypatch):
    monkeypatch.delenv("REPO_URL", raising=False)
    with pytest.raises(rn.ConfigError, match="REPO_URL"):
        rn.settings()
    monkeypatch.setenv("REPO_URL", "https://github.com/you/kyrbeis")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(rn.ConfigError, match="GITHUB_TOKEN"):
        rn.settings()
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_x")
    monkeypatch.setenv("RUN_AT", "07:30")
    assert rn.settings()["run_at"] == (7, 30)


def test_main_reports_bad_settings_instead_of_crashing(monkeypatch, caplog):
    monkeypatch.delenv("REPO_URL", raising=False)
    assert rn.main(["once"]) == 2
    assert "REPO_URL" in caplog.text


@pytest.mark.skipif(os.name == "nt", reason="the helper runs inside the Linux container")
def test_git_askpass_answers_from_the_token():
    script = Path(__file__).resolve().parent.parent / "docker" / "git-askpass.sh"
    env = {**os.environ, "GITHUB_TOKEN": "github_pat_secret"}

    def ask(prompt):
        return subprocess.run(["sh", str(script), prompt], env=env, capture_output=True, text=True).stdout.strip()

    assert ask("Username for 'https://github.com': ") == "x-access-token"
    assert ask("Password for 'https://x-access-token@github.com': ") == "github_pat_secret"
    assert b"\r" not in script.read_bytes()  # Linux line endings, or sh can't run it


def test_a_sleeping_computer_still_collects_soon_after_waking(github, tmp_path):
    """The container's timer pauses while the PC sleeps. Short naps against the real clock
    mean that after waking at 10:00 (past the 06:17 time) it collects within one nap."""
    cfg = cfg_for(github, tmp_path)
    clock = iter([at(24, 1), at(24, 10)])  # 01:00, then the PC sleeps and wakes at 10:00
    slept = []
    rn.serve(cfg, clock=lambda: next(clock), sleep=slept.append, max_loops=2, scrape=new_data, retry_delay=0)
    assert slept == [rn.CHECK_EVERY]  # napped, never one 5-hour sleep
    assert git(github, "log", "-1", "--format=%s", "main").startswith("data: update ")


def test_naps_are_never_longer_than_the_check_interval(github, tmp_path):
    cfg = cfg_for(github, tmp_path)
    slept = []
    rn.serve(cfg, clock=lambda: at(24, 1), sleep=slept.append, max_loops=3)
    assert slept and all(s <= rn.CHECK_EVERY for s in slept)
