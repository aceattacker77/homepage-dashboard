import os
import subprocess
from datetime import date, datetime, timedelta, timezone

import pytest

import second_brain as sb

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 27, 20, 0, tzinfo=SGT)          # Sunday evening
MONDAY = datetime(2026, 9, 21, 0, 0, tzinfo=SGT)


def write(vault, rel, text="# Title\n\nBody text.\n"):
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def git(vault, *args, when=None):
    env = dict(os.environ)
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=vault, env=env, check=True, capture_output=True)


@pytest.fixture
def no_parent_repo(tmp_path, monkeypatch):
    # Stop git from discovering a repo above tmp_path.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


def test_note_pool_includes_and_excludes(tmp_path):
    for rel in ["notes/a.md", "notes/deep/b.md", "decisions/d.md", "reviews/r.md",
                "identity/USER.md", "open-questions.md", "projects/p/STATUS.md",
                "inbox/cap.md", "templates/t.md", "README.md", "AGENTS.md",
                "identity/USER.proposed.md", "projects/p/other.md"]:
        write(tmp_path, rel)
    assert sb.note_pool(tmp_path) == [
        "decisions/d.md", "identity/USER.md", "notes/a.md", "notes/deep/b.md",
        "open-questions.md", "projects/p/STATUS.md", "reviews/r.md",
    ]


def test_pick_note_is_stable_per_day_and_varies():
    pool = [f"notes/{i}.md" for i in range(50)]
    day = date(2026, 9, 27)
    assert sb.pick_note(pool, day) == sb.pick_note(list(pool), day)
    picks = {sb.pick_note(pool, day + timedelta(days=i)) for i in range(14)}
    assert len(picks) > 1


def test_pick_note_empty_pool():
    assert sb.pick_note([], date(2026, 9, 27)) is None


def test_parse_note_strips_front_matter_and_markup():
    text = ("---\ncaptured: 2026-09-27\ntags: []\n---\n\n# Model split\n\n"
            "- We use **Sonnet** for [[worker|the worker]] and [docs](http://x).\n"
            "> Quoted `code` line.\n")
    title, excerpt = sb.parse_note(text, "fallback")
    assert title == "Model split"
    assert excerpt == "We use Sonnet for the worker and docs. Quoted code line."


def test_parse_note_truncates_long_excerpt():
    _, excerpt = sb.parse_note("# T\n\n" + "word " * 100, "f")
    assert len(excerpt) == sb.EXCERPT_CHARS
    assert excerpt.endswith("…")


def test_parse_note_front_matter_only():
    assert sb.parse_note("---\na: 1\n---\n", "USER") == ("USER", "")


def test_parse_note_no_heading_uses_fallback():
    assert sb.parse_note("Just a line.\r\n", "open-questions") == ("open-questions", "Just a line.")


def test_obsidian_uri_encodes_reserved_characters():
    assert sb.obsidian_uri("second-brain") == "obsidian://open?vault=second-brain"
    assert (sb.obsidian_uri("second-brain", "notes/C# & Rust ✓.md")
            == "obsidian://open?vault=second-brain&file=notes%2FC%23%20%26%20Rust%20%E2%9C%93")


def test_week_start_local():
    assert sb.week_start_local(NOW) == MONDAY


def test_added_since_uses_git_history(tmp_path, no_parent_repo):
    git(tmp_path, "init", "-q")
    write(tmp_path, "notes/old.md")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "old", when="2026-09-01T10:00:00+08:00")
    write(tmp_path, "inbox/new.md")
    write(tmp_path, "templates/tpl.md")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "new", when="2026-09-23T10:00:00+08:00")
    write(tmp_path, "notes/untracked.md")          # created now, not committed
    paths, source = sb.added_since(tmp_path, MONDAY)
    assert source == "git"
    assert paths == ["inbox/new.md", "notes/untracked.md"]


def test_git_exe_prefers_real_binary_over_cmd_launcher(tmp_path, monkeypatch):
    # Git for Windows' cmd\git.exe is a launcher; killing it on timeout leaves
    # the real git running and holding the pipe.
    launcher = tmp_path / "Git" / "cmd" / "git.exe"
    real = tmp_path / "Git" / "mingw64" / "bin" / "git.exe"
    for p in (launcher, real):
        p.parent.mkdir(parents=True)
        p.write_bytes(b"")
    monkeypatch.setattr(sb.shutil, "which", lambda _name: str(launcher))
    assert sb._git_exe() == str(real)
    real.unlink()
    assert sb._git_exe() == str(launcher)


def test_added_since_without_git_falls_back_to_mtime(tmp_path, no_parent_repo):
    write(tmp_path, "notes/fresh.md")
    paths, source = sb.added_since(tmp_path, MONDAY)
    assert source == "mtime"
    assert paths == ["notes/fresh.md"]


def test_build_second_brain_shape(tmp_path, no_parent_repo):
    write(tmp_path, "decisions/2026-09-23-model-split.md", "# Model split\n\nWorker on Sonnet.\n")
    write(tmp_path, "inbox/cap.md")
    out = sb.build_second_brain(tmp_path, "second-brain", NOW)
    assert out["note_title"] == "Model split"
    assert out["note_folder"] == "decisions"
    assert out["note_uri"].endswith("file=decisions%2F2026-09-23-model-split")
    assert out["added_this_week"] == 2
    assert out["added_label"] == "2 · 1 decisions · 1 inbox"
    assert [i["href"] for i in out["items"]] == [out["note_uri"], out["note_uri"], out["vault_uri"]]


def test_added_label_shows_top_two_folders(tmp_path, no_parent_repo):
    for rel in ["projects/a/STATUS.md", "projects/b/STATUS.md", "projects/c/STATUS.md",
                "README.md", "AGENTS.md", "inbox/x.md", "reviews/r.md"]:
        write(tmp_path, rel)
    out = sb.build_second_brain(tmp_path, "second-brain", NOW)
    assert out["added_label"] == "7 · 3 projects · 2 root"
    assert out["added_breakdown"] == "1 inbox · 3 projects · 1 reviews · 2 root"


def _pool_vault(vault, n=8):
    for i in range(n):
        write(vault, f"notes/n{i}.md", f"# Note {i}\n\nBody {i}.\n")


def test_note_of_day_survives_new_notes(tmp_path, no_parent_repo):
    vault, state = tmp_path / "v", str(tmp_path / "state" / "note.json")
    _pool_vault(vault)
    first = sb.build_second_brain(vault, "sb", NOW, state)["note_path"]
    for i in range(8, 20):                      # a busy evening of captures
        write(vault, f"reviews/r{i}.md")
        assert sb.build_second_brain(vault, "sb", NOW, state)["note_path"] == first


def test_note_of_day_changes_next_day(tmp_path, no_parent_repo):
    vault, state = tmp_path / "v", str(tmp_path / "note.json")
    _pool_vault(vault, 50)
    picks = {sb.build_second_brain(vault, "sb", NOW + timedelta(days=d), state)["note_path"]
             for d in range(10)}
    assert len(picks) > 1


def test_note_of_day_repicks_when_note_removed(tmp_path, no_parent_repo):
    vault, state = tmp_path / "v", str(tmp_path / "note.json")
    _pool_vault(vault)
    first = sb.build_second_brain(vault, "sb", NOW, state)["note_path"]
    (vault / first).unlink()
    second = sb.build_second_brain(vault, "sb", NOW, state)["note_path"]
    assert second and second != first


def test_note_of_day_ignores_corrupt_state(tmp_path, no_parent_repo):
    vault, state = tmp_path / "v", tmp_path / "note.json"
    _pool_vault(vault)
    state.write_text("{nope", encoding="utf-8")
    out = sb.build_second_brain(vault, "sb", NOW, str(state))
    assert out["note_path"] == sb.pick_note(sb.note_pool(vault), NOW.date())


def test_build_second_brain_empty_vault(tmp_path, no_parent_repo):
    out = sb.build_second_brain(tmp_path, "second-brain", NOW)
    assert out["note_title"] == "No notes yet"
    assert out["added_this_week"] == 0
    assert out["items"][0]["href"] == out["vault_uri"]


def test_build_second_brain_missing_vault(tmp_path):
    with pytest.raises(FileNotFoundError):
        sb.build_second_brain(tmp_path / "nope", "second-brain", NOW)
