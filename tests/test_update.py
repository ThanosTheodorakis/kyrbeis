"""The daily collector (scraper/update.py), tested with real git and a local stand-in for GitHub."""

import os
import subprocess
from pathlib import Path

import pytest

from scraper import update as up


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """A bare 'GitHub' repository and a clone of it standing in for your computer."""
    for k, v in {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }.items():
        monkeypatch.setenv(k, v)
    remote = tmp_path / "github.git"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(remote))
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "--quiet", "--initial-branch=main")
    (seed / "data").mkdir()
    (seed / "data" / "items.json").write_text("[]\n", encoding="utf-8")
    (seed / "README.md").write_text("Κύρβεις\n", encoding="utf-8")
    git(seed, "add", "-A")
    git(seed, "commit", "--quiet", "-m", "init")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "--quiet", "origin", "main")
    pc = tmp_path / "pc"
    git(tmp_path, "clone", "--quiet", str(remote), str(pc))
    return remote, pc


def remote_messages(remote: Path) -> list[str]:
    return git(remote, "log", "--format=%s", "main").splitlines()


def writes(text: str):
    def scrape(root: Path, site_url: str, contact: str) -> int:
        (root / "data" / "items.json").write_text(text, encoding="utf-8")
        return 0

    return scrape


def test_new_data_is_committed_and_pushed(repos):
    remote, pc = repos
    assert up.update(pc, scrape=writes('[{"title": "Προθεσμία ΕΝΦΙΑ"}]\n'), retry_delay=0) == 0
    assert remote_messages(remote)[0].startswith("data: update ")
    assert "ΕΝΦΙΑ" in git(remote, "show", "main:data/items.json")


def test_no_change_means_no_commit(repos):
    remote, pc = repos
    assert up.update(pc, scrape=writes("[]\n"), retry_delay=0) == 0
    assert remote_messages(remote) == ["init"]


def test_failed_scrape_keeps_the_old_data(repos):
    remote, pc = repos
    assert up.update(pc, scrape=lambda *a: 1, retry_delay=0) == 1
    assert remote_messages(remote) == ["init"]


def test_someone_else_pushing_meanwhile_is_handled(repos, tmp_path):
    remote, pc = repos

    def scrape_while_github_changes(root, site_url, contact):
        other = tmp_path / "other"
        git(tmp_path, "clone", "--quiet", str(remote), str(other))
        (other / "README.md").write_text("Κύρβεις, edited on GitHub\n", encoding="utf-8")
        git(other, "commit", "--quiet", "-am", "edit on GitHub")
        git(other, "push", "--quiet")
        return writes('[{"title": "new"}]\n')(root, site_url, contact)

    assert up.update(pc, scrape=scrape_while_github_changes, retry_delay=0) == 0
    messages = remote_messages(remote)
    assert messages[0].startswith("data: update ") and "edit on GitHub" in messages


def test_no_push_commits_locally_only(repos):
    remote, pc = repos
    assert up.update(pc, scrape=writes('[{"title": "x"}]\n'), push=False) == 0
    assert remote_messages(remote) == ["init"]
    assert git(pc, "log", "-1", "--format=%s").startswith("data: update ")


def test_a_second_run_is_skipped_while_one_is_running(repos):
    remote, pc = repos
    with up.Lock(pc):
        assert up.update(pc, scrape=writes('[{"title": "x"}]\n'), retry_delay=0) == 0
    assert remote_messages(remote) == ["init"]  # skipped, nothing pushed
    assert not (pc / up.LOCK_NAME).exists()


def test_a_lock_left_by_a_crash_is_cleared(repos):
    remote, pc = repos
    lock = pc / up.LOCK_NAME
    lock.write_text("12345", encoding="utf-8")
    old = lock.stat().st_mtime - up.STALE_LOCK_SECONDS - 60
    os.utime(lock, (old, old))
    assert up.update(pc, scrape=writes('[{"title": "x"}]\n'), retry_delay=0) == 0
    assert remote_messages(remote)[0].startswith("data: update ")


def test_the_scraper_gets_the_site_address_and_contact(repos, monkeypatch):
    remote, pc = repos
    git(pc, "remote", "set-url", "origin", "https://github.com/Example-User/kyrbeis.git")
    git(pc, "remote", "set-url", "--push", "origin", str(remote))
    monkeypatch.delenv("KYRBEIS_CONTACT", raising=False)
    seen = {}

    def scrape(root, site_url, contact):
        seen.update(site=site_url, contact=contact)
        return 0

    up.update(pc, scrape=scrape, push=False)
    assert seen == {
        "site": "https://example-user.github.io/kyrbeis/",
        "contact": "https://github.com/Example-User/kyrbeis/issues",
    }


@pytest.mark.parametrize(
    "remote,site",
    [
        ("https://github.com/example-user/kyrbeis.git", "https://example-user.github.io/kyrbeis/"),
        ("https://github.com/example-user/kyrbeis", "https://example-user.github.io/kyrbeis/"),
        ("git@github.com:example-user/kyrbeis.git", "https://example-user.github.io/kyrbeis/"),
        ("/some/local/path.git", ""),
    ],
)
def test_github_addresses(remote, site):
    assert up.github_addresses(remote)[0] == site


def test_a_folder_that_is_not_a_git_repository_gives_a_clear_error(tmp_path, caplog):
    plain = tmp_path / "unzipped"
    plain.mkdir()
    called = []
    assert up.update(plain, scrape=lambda *a: called.append(1) or 0) == 1
    assert not called  # stopped before scraping
    assert "not a git repository" in caplog.text
