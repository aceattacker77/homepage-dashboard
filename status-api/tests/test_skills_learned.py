import json
import os
import shutil
import time
from datetime import date, datetime

import skills_learned as sl

TODAY = date(2026, 9, 27)  # a Sunday; week starts Mon 2026-09-21


def _ts(d):
    return time.mktime(datetime(d.year, d.month, d.day, 12, 0).timetuple())


def make_skill(tree, *parts, on=None):
    """Create tree/<parts>/SKILL.md, back-dated to `on` (a date)."""
    skill_dir = os.path.join(tree, *parts)
    os.makedirs(skill_dir, exist_ok=True)
    path = os.path.join(skill_dir, "SKILL.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\nname: x\n---\n")
    if on is not None:
        os.utime(path, (_ts(on), _ts(on)))
    return skill_dir


def test_collect_dedupes_names_across_trees(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    make_skill(a, "productivity", "capture")
    make_skill(b, "capture")
    make_skill(b, "file-cleanup")
    found = sl.collect_skills([a, b, str(tmp_path / "missing")])
    assert sorted(found) == ["capture", "file-cleanup"]
    assert len(found["capture"]) == 2


def test_seed_date_uses_earliest_copy(tmp_path):
    old = make_skill(str(tmp_path / "a"), "capture", on=date(2026, 9, 10))
    new = make_skill(str(tmp_path / "b"), "capture", on=date(2026, 9, 26))
    assert sl.seed_date([new, old], TODAY) == date(2026, 9, 10)


def test_seed_date_empty_falls_back_to_today(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert sl.seed_date([str(empty)], TODAY) == TODAY


def test_bundled_names_excluded_from_counts(tmp_path):
    user, bundled = str(tmp_path / "user"), str(tmp_path / "bundled")
    make_skill(bundled, "web", "arxiv")
    make_skill(user, "arxiv", on=date(2026, 9, 22))
    make_skill(user, "capture", on=date(2026, 9, 22))
    ledger = str(tmp_path / "state" / "ledger.json")
    out = sl.build_skills_learned([user], [bundled], ledger, TODAY)
    assert out["total"] == 1
    assert out["latest"] == "capture"
    saved = json.load(open(ledger, encoding="utf-8"))
    assert saved["skills"]["arxiv"]["bundled"] is True


def test_first_seen_is_frozen(tmp_path):
    user = str(tmp_path / "user")
    skill_dir = make_skill(user, "capture", on=date(2026, 9, 1))
    ledger = str(tmp_path / "ledger.json")
    sl.build_skills_learned([user], [], ledger, TODAY)
    # Skill deleted and re-created today (e.g. restored from a backup copy).
    shutil.rmtree(skill_dir)
    make_skill(user, "capture")
    out = sl.build_skills_learned([user], [], ledger, TODAY)
    saved = json.load(open(ledger, encoding="utf-8"))
    assert saved["skills"]["capture"]["first_seen"] == "2026-09-01"
    assert out["this_week"] == 0


def test_corrupt_ledger_is_rebuilt(tmp_path):
    user = str(tmp_path / "user")
    make_skill(user, "capture", on=date(2026, 9, 26))
    ledger = tmp_path / "ledger.json"
    ledger.write_text("{not json", encoding="utf-8")
    out = sl.build_skills_learned([user], [], str(ledger), TODAY)
    assert out["total"] == 1
    assert json.loads(ledger.read_text(encoding="utf-8"))["version"] == 1


def test_summary_week_buckets():
    ledger = {"version": 1, "skills": {
        "a": {"first_seen": "2026-09-21", "bundled": False},  # Mon this week
        "b": {"first_seen": "2026-09-27", "bundled": False},  # today
        "c": {"first_seen": "2026-09-20", "bundled": False},  # Sun last week
        "d": {"first_seen": "2026-09-27", "bundled": True},   # bundled: ignored
    }}
    out = sl.summarise(ledger, TODAY)
    assert (out["this_week"], out["last_week"], out["total"]) == (2, 1, 3)
    assert out["weekly_counts"] == [0, 0, 0, 0, 0, 0, 1, 2]
    assert out["latest_label"] == "b · today"
    assert [i["name"] for i in out["items"]] == ["b", "a", "c"]


def test_no_skills():
    out = sl.summarise({"version": 1, "skills": {}}, TODAY)
    assert out["total"] == 0
    assert out["latest"] == "none yet"
    assert out["trend"] == "▁" * 8
    assert out["items"] == []


def test_sparkline_scales_to_max():
    # levels: 0 -> ▁; else SPARK[1 + round(n / max * 6)]  (round(1.5) == 2)
    assert sl.sparkline([0, 1, 2, 4]) == "▁▄▅█"
    assert sl.sparkline([0, 0]) == "▁▁"


def test_week_start_is_monday():
    assert sl.week_start(TODAY) == date(2026, 9, 21)
    assert sl.week_start(date(2026, 9, 21)) == date(2026, 9, 21)
