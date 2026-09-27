"""Skills-learned tracker behind the /skills-learned endpoint.

A skill is a folder containing SKILL.md, keyed by folder name, so the same
skill copied into several profile trees counts once. "Learned" means the name
is not shipped in Hermes' bundled skill trees. Each skill's first-seen date is
frozen in a small JSON ledger the first time it is seen, so later edits,
copies and backup restores cannot move it.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

SPARK = "▁▂▃▄▅▆▇█"


def collect_skills(trees):
    """{name: [skill_dir, ...]} across every tree that exists."""
    found = {}
    for tree in trees:
        if not os.path.isdir(tree):
            continue
        for root, dirs, files in os.walk(tree):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if "SKILL.md" in files:
                found.setdefault(os.path.basename(root), []).append(root)
    return found


def seed_date(skill_dirs, today):
    """Earliest creation/modification time of SKILL.md across all copies.

    Only SKILL.md: other files can be vendored (a skill's .venv keeps each
    package's release date) and would drag the date back by months. On
    Windows st_ctime is the creation time; min() with st_mtime also covers
    copies that kept an older modification time.
    """
    earliest = None
    for skill_dir in skill_dirs:
        try:
            st = os.stat(os.path.join(skill_dir, "SKILL.md"))
        except OSError:
            continue
        t = min(st.st_ctime, st.st_mtime)
        earliest = t if earliest is None else min(earliest, t)
    if earliest is None:
        return today
    return datetime.fromtimestamp(earliest).date()


def _valid_entry(entry):
    if not isinstance(entry, dict) or not isinstance(entry.get("first_seen"), str):
        return False
    try:
        date.fromisoformat(entry["first_seen"])
    except ValueError:
        return False
    return True


def load_ledger(path):
    """The ledger, with malformed entries dropped so they re-seed."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("skills"), dict):
            data["skills"] = {k: v for k, v in data["skills"].items() if _valid_entry(v)}
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "skills": {}}


def save_ledger(path, ledger):
    """Atomic write so a crash mid-save never leaves half a ledger."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def update_ledger(ledger, skills, bundled, today):
    """Record unseen names; never move an existing first_seen. True if changed."""
    changed = False
    for name, dirs in skills.items():
        if name in ledger["skills"]:
            continue
        ledger["skills"][name] = {
            "first_seen": seed_date(dirs, today).isoformat(),
            "bundled": name in bundled,
        }
        changed = True
    return changed


def week_start(d):
    return d - timedelta(days=d.weekday())


def sparkline(counts):
    top = max(counts) if counts else 0
    if top == 0:
        return SPARK[0] * len(counts)
    return "".join(SPARK[0] if n == 0 else SPARK[1 + round(n / top * 6)] for n in counts)


def ago(d, today):
    days = (today - d).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days}d ago"


def summarise(ledger, today, weeks=8):
    learned = sorted(
        ((date.fromisoformat(v["first_seen"]), name)
         for name, v in ledger["skills"].items() if not v.get("bundled")),
        reverse=True,
    )
    this_monday = week_start(today)
    counts = []
    for i in range(weeks - 1, -1, -1):
        start = this_monday - timedelta(weeks=i)
        end = start + timedelta(days=7)
        counts.append(sum(1 for d, _ in learned if start <= d < end))
    latest = learned[0] if learned else None
    return {
        "this_week": counts[-1],
        "last_week": counts[-2],
        "total": len(learned),
        "trend": sparkline(counts),
        "weekly_counts": counts,
        "latest": latest[1] if latest else "none yet",
        "latest_label": f"{latest[1]} · {ago(latest[0], today)}" if latest else "none yet",
        "items": [{"name": name, "label": ago(d, today)} for d, name in learned[:5]],
    }


def build_skills_learned(skill_trees, bundled_trees, ledger_path, today):
    ledger = load_ledger(ledger_path)
    bundled = set(collect_skills(bundled_trees))
    if update_ledger(ledger, collect_skills(skill_trees), bundled, today):
        try:
            save_ledger(ledger_path, ledger)
        except OSError:
            # e.g. the file is held open by an editor or AV scanner on Windows.
            # Serve this run's numbers; the next refresh retries the save.
            pass
    return summarise(ledger, today)
