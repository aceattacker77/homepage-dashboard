# Mind Cards + Soft Glass Restyle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two Homepage cards — "Skills Learned" (new Hermes skills per week) and "Second Brain" (note of the day + notes added this week) — and restyle the dashboard in a "soft glass" look.

**Architecture:** Both cards are Homepage `customapi` widgets backed by two new endpoints on the existing host-run FastAPI status API (`status-api/status_api.py`, port 8787), which already backs five cards the same way. Each endpoint's logic lives in its own small module (`skills_learned.py`, `second_brain.py`) with pure, testable functions; `status_api.py` only wires routes and caches. The restyle is `settings.yaml` + a rewritten `config/custom.css` targeting Homepage's own semantic classes.

**Tech Stack:** Python 3.11 (status-api `.venv`), FastAPI 0.141, pytest + httpx (new, test-only), git 2.48 (host), Homepage `ghcr.io/gethomepage/homepage:latest` in Docker.

**Spec:** No separate spec file. The design was agreed in chat on 2026-09-27 and is recorded in "Design decisions" below. Executors should treat that section as the spec.

## Design decisions (the spec)

- **Nothing new is scheduled.** The status API already runs at logon and computes on request with TTL caches. The new endpoints follow that pattern.
- **Skills Learned**
  - A skill is a folder containing `SKILL.md`, keyed by folder name. Names are merged across `hermes/skills/` and every `hermes/profiles/*/skills/`, so the same skill in three trees counts once.
  - "Learned" means the name is not in Hermes' bundled trees (`hermes-agent/skills/`, `hermes-agent/optional-skills/`). On 2026-09-27 that is 7 of 65 names: capture, everything-search, file-cleanup, gateway-config, hermes-agent-handoff, homepage-dashboard-widgets, mcp-server-integration.
  - First-seen dates are frozen in `status-api/state/skills_ledger.json`. The first sighting is seeded from the earliest creation or modification time of any file in any copy. After that, later edits, copies and backup restores cannot move the date.
  - Weeks run Monday to Sunday in the host's local time.
  - Card fields: This week, Last week, Learned (total), 8-week text sparkline, Latest.
- **Second Brain**
  - The vault is `C:\Users\Admin\second-brain`, confirmed by the user and registered in Obsidian as vault name `second-brain`.
  - The API only reads the vault: it reads files and runs `git log` / `git ls-files`. It never writes to or commits in the vault (see the vault's `AGENTS.md`).
  - Note pool (user-approved): `notes/**`, `decisions/**`, `reviews/**`, `identity/**`, `open-questions.md`, `projects/*/STATUS.md`. Excluded: `inbox/`, `templates/`, `README.md`, `AGENTS.md`, `*.proposed.md`.
  - Note of the day = `sha256(today ISO date) mod len(sorted pool)`. It is the same all day and changes at local midnight, with no stored state.
  - "Added this week" = `.md` files added in git since Monday 00:00 local (`--diff-filter=A`), plus untracked `.md` files created since then, minus `templates/`, counting only files that still exist. If git is unavailable or the folder is not a repo, file creation times are used instead and `added_source` says `mtime`.
  - Clicking a note opens it in Obsidian through `obsidian://open?vault=second-brain&file=<percent-encoded path without .md>`.
- **Soft glass restyle** (user-chosen)
  - Keep the title `CYBER://HUB` (user decision).
  - `cardBlur: md`; indigo/slate/teal gradient background; translucent cards (~6% white fill, 1px ~10% white border, 16px radius, soft shadow, 2px hover lift).
  - Inter font; muted slate labels with near-white values; one lavender accent.
  - Remove the old rules that put a border on every `div[class*="bg-"]` and force all text to cyan.
- **Layout** (balanced; user-approved 2026-09-27)
  - Root cause of today's lopsided page: `style: grid` is not a Homepage layout style. Only `row` and the default `column` exist, so every group currently falls back to `column`: four side-by-side, one-card-wide stacks, with Downloads 222px tall and YouTube 2192px tall (measured at 1345px width). The `columns:` values are being ignored.
  - Every service group becomes `style: row`, in this order: each row is full width, and cards sit side by side.
    1. **Hermes Agents**, 4 columns: Status, Credits, Cron, GPU.
    2. **Mind**, 3 columns: Skills Learned, Second Brain, Headlines (moved out of Hermes Agents).
    3. **Infrastructure**, 3 columns: Homepage, FreshRSS, JDownloader 2. The single-card Downloads group is merged in here so it doesn't leave half an empty row.
    4. **YouTube**, 3 columns (6 cards = 2 full rows), `initiallyCollapsed: true` (user-approved).
  - The bookmark groups (Developer, Social, Entertainment) are already an even row of 3 and stay as they are.
  - `useEqualHeights: true` globally, so cards in a row line up.
  - Dead settings removed while tidying (verified against gethomepage.dev/configs/settings):
    - The `search:` block in settings.yaml does nothing, because the live search is the DuckDuckGo widget in widgets.yaml.
    - `providers: status: style: dot` is the wrong key. The correct one is `statusStyle: "dot"`, so status dots are currently not applied.
- **Housekeeping**
  - Move the JDownloader username and password out of `services.yaml` into a gitignored compose `.env`.
  - Then put `C:\Users\Admin\docker\homepage` under git, so every later task can be committed and reverted.

## Global Constraints

- Status API stays read-only toward Hermes and the vault. Its only write is its own `status-api/state/skills_ledger.json`.
- Widget URLs use `{{HOMEPAGE_VAR_STATUS_API}}` (= `http://host.docker.internal:8787`), never `localhost`. Homepage fetches server-side from inside its container.
- Never use `os.kill(pid, 0)` on Windows (it terminates the process). This plan needs no PID checks, and nothing here should add one.
- No secrets in any committed file. `.env` is gitignored before the first commit.
- CSS selectors target Homepage's semantic classes, verified live on 2026-09-27: `.service-card`, `.service-container`, `.service-block`, `.service-group-name`, `.service-name`, `.service-title-text`, `.service-description`, `.information-widget-resource`, `#information-widgets`, `.bookmark-group-name`.
- Vault path and name come from env vars `SECOND_BRAIN_DIR` (default `C:\Users\Admin\second-brain`) and `SECOND_BRAIN_VAULT` (default `second-brain`).
- Test runner: `status-api/.venv/Scripts/python.exe -m pytest` run from `C:\Users\Admin\docker\homepage\status-api`.

## Review Focus

1. **Note paths with spaces, `#`, `&`, unicode or subfolders** must produce an `obsidian://` URI that opens the right note, with every reserved character percent-encoded, `/` included. Pinned by `test_obsidian_uri_encodes_reserved_characters` (Task 3).
2. **Notes with only front-matter, no heading or an empty body** must render a title from the filename and an empty excerpt without crashing. Pinned by `test_parse_note_front_matter_only` and `test_parse_note_no_heading_uses_fallback` (Task 3).
3. **The vault is not a git repo, git is missing, or the vault folder was moved** must give a working card (mtime fallback, or an "unavailable" row), never a 500 that blanks the card. Pinned by `test_added_since_without_git_falls_back_to_mtime` (Task 3) and `test_second_brain_route_missing_vault` (Task 4).
4. **The same skill in several trees with different timestamps, later edited or restored from a backup** must count once, with a first-seen date that never moves. Pinned by `test_collect_dedupes_names_across_trees`, `test_seed_date_uses_earliest_copy` and `test_first_seen_is_frozen` (Task 2).
5. **An empty or corrupt ledger or pool** (fresh install, half-written JSON, empty vault) must show zeros or "none yet" / "No notes yet", with no ZeroDivision or JSON error. Pinned by `test_corrupt_ledger_is_rebuilt`, `test_no_skills` (Task 2) and `test_pick_note_empty_pool` (Task 3).

---

## File Structure

| Path (under `C:\Users\Admin\docker\homepage`) | Action | Responsibility |
|---|---|---|
| `.env` | Create (gitignored) | `JD_USERNAME`, `JD_PASSWORD` for compose substitution |
| `.gitignore` | Create | Keep secrets, venv, logs and ledger state out of git |
| `docker-compose.yml` | Modify | Pass `HOMEPAGE_VAR_JD_USERNAME` / `HOMEPAGE_VAR_JD_PASSWORD` |
| `status-api/skills_learned.py` | Create | Skill discovery, ledger, weekly summary (pure functions) |
| `status-api/second_brain.py` | Create | Note pool, daily pick, note parsing, git "added" count |
| `status-api/status_api.py` | Modify | Config constants, caches, `/skills-learned`, `/second-brain` routes |
| `status-api/requirements-dev.txt` | Create | `pytest`, `httpx` |
| `status-api/tests/conftest.py` | Create | Put `status-api/` on `sys.path` |
| `status-api/tests/test_skills_learned.py` | Create | Unit tests for `skills_learned` |
| `status-api/tests/test_second_brain.py` | Create | Unit tests for `second_brain` |
| `status-api/tests/test_routes.py` | Create | Route tests through FastAPI `TestClient` |
| `status-api/README.md` | Modify | Document the two endpoints, the ledger and env vars |
| `config/services.yaml` | Modify | Mind group, JDownloader secrets via `{{HOMEPAGE_VAR_…}}` |
| `config/settings.yaml` | Modify | `cardBlur: md`, new layout entries |
| `config/custom.css` | Rewrite | Soft glass theme |

---

### Task 1: Move JDownloader credentials out of config, then put the folder under git

**Files:**
- Create: `C:\Users\Admin\docker\homepage\.env`
- Create: `C:\Users\Admin\docker\homepage\.gitignore`
- Modify: `C:\Users\Admin\docker\homepage\docker-compose.yml` (`environment:` list)
- Modify: `C:\Users\Admin\docker\homepage\config\services.yaml` (JDownloader `widget:` block at the end of the file)

**Interfaces:**
- Consumes: nothing
- Produces: a git repo at `C:\Users\Admin\docker\homepage` that later tasks commit into; env vars `HOMEPAGE_VAR_JD_USERNAME`, `HOMEPAGE_VAR_JD_PASSWORD` inside the container.

- [ ] **Step 1: Create `.env` holding the current values**

Copy the current `username:` and `password:` values from the JDownloader block in `config/services.yaml` into `.env` next to `docker-compose.yml`. Do not paste the values into chat, commit messages or this plan.

```dotenv
# Read by docker compose for ${...} substitution. Gitignored -- never commit.
JD_USERNAME=<value currently in services.yaml username:>
JD_PASSWORD=<value currently in services.yaml password:>
```

- [ ] **Step 2: Pass them into the container**

In `docker-compose.yml`, append to the `environment:` list:

```yaml
      # JDownloader (my.jdownloader.org) login for the Downloads card. Values
      # live in the gitignored .env next to this file.
      - HOMEPAGE_VAR_JD_USERNAME=${JD_USERNAME}
      - HOMEPAGE_VAR_JD_PASSWORD=${JD_PASSWORD}
```

- [ ] **Step 3: Reference them from `services.yaml`**

Replace the two literal lines in the JDownloader widget with:

```yaml
          username: "{{HOMEPAGE_VAR_JD_USERNAME}}"
          password: "{{HOMEPAGE_VAR_JD_PASSWORD}}"
```

- [ ] **Step 4: Recreate the container and verify the card still loads**

Run (from `C:\Users\Admin\docker\homepage`): `docker compose up -d`
Expected: `Container homepage  Recreated` / `Started`.

Run: `docker exec homepage printenv HOMEPAGE_VAR_JD_USERNAME`
Expected: the username (not empty, not `${JD_USERNAME}`).

Open `http://localhost:3000`. Expected: the JDownloader 2 card shows its usual download stats, not an API error.

- [ ] **Step 5: Create `.gitignore`**

```gitignore
# Secrets for compose substitution
.env
# Status API runtime artefacts
status-api/.venv/
status-api/*.log
status-api/*.log.1
status-api/state/
__pycache__/
.pytest_cache/
# Homepage's own logs
config/logs/
```

- [ ] **Step 6: Init the repo and confirm no secret is staged**

```bash
cd /c/Users/Admin/docker/homepage
git init -q
git add -A
git status --short
git grep --cached -nE "password:|JD_PASSWORD=" -- . ':!docs'
```

Expected: `git status` lists no `.env`, `.venv` or `*.log` files. `git grep` prints only `config/services.yaml:…password: "{{HOMEPAGE_VAR_JD_PASSWORD}}"` and nothing containing a literal password.

- [ ] **Step 7: Commit**

```bash
git commit -m "chore: move JDownloader credentials to .env and start tracking homepage config"
```

---

### Task 2: `skills_learned` module (discovery, frozen ledger, weekly summary)

**Files:**
- Create: `status-api/skills_learned.py`
- Create: `status-api/requirements-dev.txt`
- Create: `status-api/tests/conftest.py`
- Test: `status-api/tests/test_skills_learned.py`

**Interfaces:**
- Consumes: nothing
- Produces (used by Task 4):
  - `build_skills_learned(skill_trees: list[str], bundled_trees: list[str], ledger_path: str, today: datetime.date) -> dict`
    returns `{"this_week": int, "last_week": int, "total": int, "trend": str, "weekly_counts": list[int], "latest": str, "latest_label": str, "items": list[{"name": str, "label": str}]}`
  - Helpers also imported by tests: `collect_skills`, `seed_date`, `load_ledger`, `save_ledger`, `update_ledger`, `summarise`, `sparkline`, `week_start`.

- [ ] **Step 1: Add test dependencies**

`status-api/requirements-dev.txt`:

```text
pytest>=8
httpx>=0.27
```

Run: `status-api/.venv/Scripts/python.exe -m pip install -r status-api/requirements-dev.txt`
Expected: `Successfully installed … pytest … httpx …`

`status-api/tests/conftest.py`:

```python
import os
import sys

# Tests import the status-api modules directly (they are scripts, not a package).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

- [ ] **Step 2: Write the failing tests**

`status-api/tests/test_skills_learned.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `status-api/`): `.venv/Scripts/python.exe -m pytest tests/test_skills_learned.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'skills_learned'`.

- [ ] **Step 4: Implement `status-api/skills_learned.py`**

```python
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
    """Earliest creation/modification time of any file in any copy.

    On Windows st_ctime is the creation time; min() with st_mtime also covers
    copies that kept an older modification time.
    """
    earliest = None
    for skill_dir in skill_dirs:
        for root, _dirs, files in os.walk(skill_dir):
            for name in files:
                try:
                    st = os.stat(os.path.join(root, name))
                except OSError:
                    continue
                t = min(st.st_ctime, st.st_mtime)
                earliest = t if earliest is None else min(earliest, t)
    if earliest is None:
        return today
    return datetime.fromtimestamp(earliest).date()


def load_ledger(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("skills"), dict):
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
        save_ledger(ledger_path, ledger)
    return summarise(ledger, today)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills_learned.py -q`
Expected: `10 passed`.

- [ ] **Step 6: Commit**

```bash
git add status-api/skills_learned.py status-api/requirements-dev.txt status-api/tests
git commit -m "feat(status-api): skills-learned ledger and weekly summary"
```

---

### Task 3: `second_brain` module (pool, daily pick, parsing, added-this-week)

**Files:**
- Create: `status-api/second_brain.py`
- Test: `status-api/tests/test_second_brain.py`

**Interfaces:**
- Consumes: `tests/conftest.py` from Task 2
- Produces (used by Task 4):
  - `build_second_brain(vault: str | Path, vault_name: str, now: datetime) -> dict` (`now` is timezone-aware local time). Raises `FileNotFoundError` if the vault folder is missing.
    Returns `{"note_title", "note_path", "note_folder", "note_excerpt", "note_uri", "added_this_week": int, "added_breakdown", "added_label", "added_source": "git"|"mtime", "pool_size": int, "vault_uri", "items": [3 × {"name", "label", "href"}]}`
  - Helpers imported by tests: `note_pool`, `pick_note`, `parse_note`, `obsidian_uri`, `added_since`, `week_start_local`.

- [ ] **Step 1: Write the failing tests**

`status-api/tests/test_second_brain.py`:

```python
import os
import subprocess
import time
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


def test_build_second_brain_empty_vault(tmp_path, no_parent_repo):
    out = sb.build_second_brain(tmp_path, "second-brain", NOW)
    assert out["note_title"] == "No notes yet"
    assert out["added_this_week"] == 0
    assert out["items"][0]["href"] == out["vault_uri"]


def test_build_second_brain_missing_vault(tmp_path):
    with pytest.raises(FileNotFoundError):
        sb.build_second_brain(tmp_path / "nope", "second-brain", NOW)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_second_brain.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'second_brain'`.

- [ ] **Step 3: Implement `status-api/second_brain.py`**

```python
"""Second-brain card behind the /second-brain endpoint.

Read-only against the vault: it reads Markdown files and runs `git log` /
`git ls-files`, never writes or commits. One note is picked per day from a
hash of the date, so the pick is stable all day with no stored state.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

# User-approved pool. inbox/ captures are mostly bare URLs; templates and the
# vault's own README/AGENTS are structure, not notes.
POOL_PATTERNS = (
    "notes/**/*.md",
    "decisions/**/*.md",
    "reviews/**/*.md",
    "identity/**/*.md",
    "open-questions.md",
    "projects/*/STATUS.md",
)
COUNT_EXCLUDE_PREFIXES = ("templates/", ".obsidian/", ".trash/")
EXCERPT_CHARS = 140

FRONT_MATTER = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|\Z)", re.S)
WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
LINE_PREFIX = re.compile(r"^(?:>\s*|[-*+]\s+(?:\[.\]\s+)?|\d+\.\s+)+")


def note_pool(vault):
    vault = Path(vault)
    found = set()
    for pattern in POOL_PATTERNS:
        for path in vault.glob(pattern):
            if path.is_file() and not path.name.endswith(".proposed.md"):
                found.add(path.relative_to(vault).as_posix())
    return sorted(found)


def pick_note(pool, day):
    if not pool:
        return None
    digest = hashlib.sha256(day.isoformat().encode("ascii")).hexdigest()
    return pool[int(digest, 16) % len(pool)]


def parse_note(text, fallback_title):
    body = FRONT_MATTER.sub("", text.replace("\r\n", "\n"), count=1)
    title = None
    lines = []
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if title is None and line.startswith("# "):
                title = line[2:].strip()
            continue
        lines.append(LINE_PREFIX.sub("", line))
    excerpt = " ".join(lines)
    excerpt = WIKI_LINK.sub(lambda m: m.group(2) or m.group(1), excerpt)
    excerpt = MD_LINK.sub(r"\1", excerpt)
    excerpt = re.sub(r"\*\*|__|`", "", excerpt)
    excerpt = re.sub(r"\s+", " ", excerpt).strip()
    if len(excerpt) > EXCERPT_CHARS:
        excerpt = excerpt[: EXCERPT_CHARS - 1].rstrip() + "…"
    return title or fallback_title, excerpt


def obsidian_uri(vault_name, rel_path=None):
    uri = "obsidian://open?vault=" + quote(vault_name, safe="")
    if rel_path:
        stem = rel_path[:-3] if rel_path.endswith(".md") else rel_path
        uri += "&file=" + quote(stem, safe="")
    return uri


def week_start_local(now):
    monday = now.date() - timedelta(days=now.weekday())
    return datetime.combine(monday, datetime.min.time(), tzinfo=now.tzinfo)


def _git_lines(vault, *args):
    git = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    out = subprocess.run(
        [git, "-c", "core.quotepath=off", *args],
        cwd=vault, capture_output=True, text=True, encoding="utf-8",
        timeout=10, check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def _created(path):
    st = path.stat()
    return min(st.st_ctime, st.st_mtime)  # st_ctime is creation time on Windows


def added_since(vault, since):
    """(sorted rel paths added since `since` that still exist, "git"|"mtime")."""
    vault = Path(vault)
    paths = set()
    try:
        paths.update(_git_lines(vault, "log", f"--since={since.isoformat()}",
                                "--diff-filter=A", "--name-only", "--format=", "--", "*.md"))
        candidates = _git_lines(vault, "ls-files", "--others", "--exclude-standard", "--", "*.md")
        source = "git"
    except (OSError, subprocess.SubprocessError):
        candidates = [p.relative_to(vault).as_posix() for p in vault.rglob("*.md")]
        source = "mtime"
    cutoff = since.timestamp()
    for rel in candidates:
        try:
            if _created(vault / rel) >= cutoff:
                paths.add(rel)
        except OSError:
            continue
    kept = sorted(p for p in paths
                  if (vault / p).is_file() and not p.startswith(COUNT_EXCLUDE_PREFIXES))
    return kept, source


def build_second_brain(vault, vault_name, now):
    vault = Path(vault)
    if not vault.is_dir():
        raise FileNotFoundError(f"vault not found: {vault}")

    pool = note_pool(vault)
    rel = pick_note(pool, now.date())
    vault_uri = obsidian_uri(vault_name)
    if rel:
        text = (vault / rel).read_text(encoding="utf-8", errors="replace")
        title, excerpt = parse_note(text, Path(rel).stem)
        folder = Path(rel).parent.as_posix() if "/" in rel else "vault root"
        note_uri = obsidian_uri(vault_name, rel)
    else:
        title, excerpt, folder, note_uri = "No notes yet", "", "", vault_uri

    added, source = added_since(vault, week_start_local(now))
    by_folder = Counter(p.split("/", 1)[0] if "/" in p else "root" for p in added)
    breakdown = " · ".join(f"{n} {name}" for name, n in sorted(by_folder.items()))
    added_label = f"{len(added)} · {breakdown}" if added else "0"

    return {
        "note_title": title,
        "note_path": rel or "",
        "note_folder": folder,
        "note_excerpt": excerpt,
        "note_uri": note_uri,
        "added_this_week": len(added),
        "added_breakdown": breakdown,
        "added_label": added_label,
        "added_source": source,
        "pool_size": len(pool),
        "vault_uri": vault_uri,
        "items": [
            {"name": title, "label": folder, "href": note_uri},
            {"name": excerpt or "—", "label": "", "href": note_uri},
            {"name": "Added this week", "label": added_label, "href": vault_uri},
        ],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_second_brain.py -q`
Expected: `14 passed`.

- [ ] **Step 5: Smoke-test against the real vault (read-only)**

```bash
cd /c/Users/Admin/docker/homepage/status-api
.venv/Scripts/python.exe -c "import json,second_brain as sb; from datetime import datetime; print(json.dumps(sb.build_second_brain(r'C:\Users\Admin\second-brain','second-brain',datetime.now().astimezone()),indent=2,ensure_ascii=False))"
git -C /c/Users/Admin/second-brain status --short
```

Expected: `pool_size` about 8, `added_source: "git"`, `added_this_week` ≥ 4 (3 inbox captures + weekly review as of 2026-09-27). The `git status` output must be the same before and after: the vault is untouched.

- [ ] **Step 6: Commit**

```bash
git add status-api/second_brain.py status-api/tests/test_second_brain.py
git commit -m "feat(status-api): second-brain note of the day and weekly additions"
```

---

### Task 4: Wire `/skills-learned` and `/second-brain` into the status API

**Files:**
- Modify: `status-api/status_api.py` (module docstring; imports; Configuration block around line 45–75; `_CACHES` at line ~91; new sections before `# 6. /health`)
- Modify: `status-api/README.md` (Endpoints table, new "Skills ledger" section, env var table)
- Test: `status-api/tests/test_routes.py`

**Interfaces:**
- Consumes: `skills_learned.build_skills_learned(...)` (Task 2), `second_brain.build_second_brain(...)` (Task 3)
- Produces (used by Task 5): `GET /skills-learned` → Task 2's dict; `GET /second-brain` → Task 3's dict, or `{"error": str, "items": [{"name": "Vault unavailable", "label": str, "href": ""}]}` with HTTP 200 when the vault is missing.

- [ ] **Step 1: Write the failing route tests**

`status-api/tests/test_routes.py`:

```python
from fastapi.testclient import TestClient

import status_api


def _reset(name):
    status_api._CACHES[name]["value"] = None
    status_api._CACHES[name]["expires"] = 0.0


def test_skills_learned_route(tmp_path, monkeypatch):
    tree = tmp_path / "skills" / "capture"
    tree.mkdir(parents=True)
    (tree / "SKILL.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(status_api, "skill_trees", lambda: [str(tmp_path / "skills")])
    monkeypatch.setattr(status_api, "BUNDLED_SKILL_TREES", [])
    monkeypatch.setattr(status_api, "SKILLS_LEDGER", str(tmp_path / "state" / "ledger.json"))
    _reset("skills")
    body = TestClient(status_api.app).get("/skills-learned").json()
    assert body["total"] == 1 and body["latest"] == "capture"


def test_second_brain_route(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("# A\n\nBody.\n", encoding="utf-8")
    monkeypatch.setattr(status_api, "SECOND_BRAIN_DIR", str(tmp_path))
    _reset("brain")
    resp = TestClient(status_api.app).get("/second-brain")
    assert resp.status_code == 200
    assert resp.json()["note_title"] == "A"


def test_second_brain_route_missing_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(status_api, "SECOND_BRAIN_DIR", str(tmp_path / "moved"))
    _reset("brain")
    resp = TestClient(status_api.app).get("/second-brain")
    assert resp.status_code == 200
    body = resp.json()
    assert "vault not found" in body["error"]
    assert body["items"][0]["name"] == "Vault unavailable"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py -q`
Expected: 3 failures (`AttributeError: … has no attribute 'skill_trees'` / 404s).

- [ ] **Step 3: Add imports and configuration to `status_api.py`**

In the import block add `import glob` (alphabetically, after `import ctypes`) and, after the `fastapi` imports:

```python
import second_brain
import skills_learned
```

At the end of the Configuration block (after `USER_AGENT = …`, before `CATEGORY_MAP`):

```python
# Skills Learned card. Names in hermes-agent's own trees are "bundled", not
# learned. The ledger is this API's only write -- its own state, not Hermes'.
BUNDLED_SKILL_TREES = [
    os.path.join(HERMES_BASE, "hermes-agent", "skills"),
    os.path.join(HERMES_BASE, "hermes-agent", "optional-skills"),
]
SKILLS_LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "skills_ledger.json")
SKILLS_CACHE_TTL = 300

# Second Brain card (read-only against the vault).
SECOND_BRAIN_DIR = os.environ.get("SECOND_BRAIN_DIR", r"C:\Users\Admin\second-brain")
SECOND_BRAIN_VAULT = os.environ.get("SECOND_BRAIN_VAULT", "second-brain")
SECOND_BRAIN_CACHE_TTL = 300


def skill_trees():
    """Base skills plus every profile's, re-globbed so new profiles appear."""
    return [os.path.join(HERMES_BASE, "skills")] + sorted(
        glob.glob(os.path.join(HERMES_PROFILES_DIR, "*", "skills")))
```

Change the caches line to:

```python
_CACHES = {name: _cache() for name in ("cron", "rss", "credits", "gpu", "skills", "brain")}
```

- [ ] **Step 4: Add the two route sections before `# 6. /health`**

```python
# --------------------------------------------------------------------------
# 7. /skills-learned
# --------------------------------------------------------------------------

@app.get("/skills-learned")
def skills_learned_route():
    return JSONResponse(cached("skills", SKILLS_CACHE_TTL, lambda: skills_learned.build_skills_learned(
        skill_trees(), BUNDLED_SKILL_TREES, SKILLS_LEDGER, datetime.now().date())))


# --------------------------------------------------------------------------
# 8. /second-brain
# --------------------------------------------------------------------------

def build_second_brain_card():
    try:
        return second_brain.build_second_brain(
            SECOND_BRAIN_DIR, SECOND_BRAIN_VAULT, datetime.now().astimezone())
    except (OSError, ValueError) as exc:
        # Keep the card rendering (with the reason) instead of a 500.
        return {"error": f"{type(exc).__name__}: {exc}",
                "items": [{"name": "Vault unavailable", "label": str(exc), "href": ""}]}


@app.get("/second-brain")
def second_brain_route():
    return JSONResponse(cached("brain", SECOND_BRAIN_CACHE_TTL, build_second_brain_card))
```

Update the module docstring's endpoint list with:

```text
  /skills-learned      new (non-bundled) Hermes skills per week
  /second-brain        note of the day + notes added this week from the vault
```

and change its "STRICTLY READ-ONLY" paragraph's last sentence to: `It only reads Hermes state files and the second-brain vault, shells out to read-only commands (nvidia-smi, git log/ls-files), and writes nothing but its own state/skills_ledger.json.`

- [ ] **Step 5: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: `27 passed`.

- [ ] **Step 6: Update `status-api/README.md`**

Add two rows to the Endpoints table:

```markdown
| `/skills-learned` | Skills Learned | `skills/` + `profiles/*/skills/` vs bundled `hermes-agent/{skills,optional-skills}`; `state/skills_ledger.json` |
| `/second-brain` | Second Brain | `C:\Users\Admin\second-brain` (files + `git log`, read-only) |
```

Add a section after "Notable implementation details":

```markdown
## Skills ledger

`state/skills_ledger.json` freezes the date each skill name was first seen.
The first sighting is seeded from the earliest creation/modification time
of any file in any copy of that skill. After that, edits, copies and backup
restores cannot move it. Delete the file to re-seed from timestamps. It is
gitignored and is this API's only write.
```

Add to the Environment variables table:

```markdown
| `SECOND_BRAIN_DIR` | `C:\Users\Admin\second-brain` | Obsidian vault folder |
| `SECOND_BRAIN_VAULT` | `second-brain` | Vault name used in `obsidian://` links |
```

- [ ] **Step 7: Restart the running API and hit the endpoints**

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*status_api.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Confirm:$false }
wscript.exe "C:\Users\Admin\docker\homepage\status-api\launch-hidden.vbs"
```

```bash
curl -s http://localhost:8787/skills-learned
curl -s http://localhost:8787/second-brain
```

Expected: `/skills-learned` shows `total: 7` (the seven learned names in Design decisions) and `latest` = `file-cleanup`. `/second-brain` shows a `note_title` from the pool and `added_source: "git"`. `status-api/state/skills_ledger.json` now exists.

- [ ] **Step 8: Commit**

```bash
git add status-api/status_api.py status-api/README.md status-api/tests/test_routes.py
git commit -m "feat(status-api): serve /skills-learned and /second-brain"
```

---

### Task 5: Mind group and balanced layout in Homepage config

**Files:**
- Modify: `config/services.yaml` (remove `Headlines` from "Hermes Agents"; add "Mind" group after it; move JDownloader 2 into "Infrastructure"; delete the "Downloads" group)
- Modify: `config/settings.yaml` (`layout:`, `cardBlur:`, `useEqualHeights:`, `statusStyle:`; remove dead `search:` and `providers:` blocks)

**Interfaces:**
- Consumes: `/skills-learned` fields `this_week`, `last_week`, `total`, `trend`, `latest_label`; `/second-brain` `items[].name/label/href` (Task 4)
- Produces: rendered cards used by Task 6's visual check.

- [ ] **Step 1: Move Headlines and add the Mind group**

Cut the whole `- Headlines:` entry (with its `widget:` block) out of `- Hermes Agents:`. Insert this group directly after the Hermes Agents group:

```yaml
# ---------------------------------------------------------------------------
# Mind: what Hermes and I have been learning. Both new cards are Custom API
# widgets on the status API (see status-api/README.md).
# ---------------------------------------------------------------------------
- Mind:
    - Skills Learned:
        icon: mdi-school-outline
        description: New Hermes skills per week
        widget:
          type: customapi
          url: "{{HOMEPAGE_VAR_STATUS_API}}/skills-learned"
          refreshInterval: 300000
          display: list
          mappings:
            - field: this_week
              label: This week
            - field: last_week
              label: Last week
            - field: total
              label: Learned
            - field: trend
              label: 8 weeks
            - field: latest_label
              label: Latest

    - Second Brain:
        icon: mdi-brain
        href: "obsidian://open?vault=second-brain"
        description: Note of the day
        widget:
          type: customapi
          url: "{{HOMEPAGE_VAR_STATUS_API}}/second-brain"
          refreshInterval: 300000
          display: dynamic-list
          mappings:
            items: items
            name: name
            label: label
            limit: 3
            target: "{href}"

    - Headlines:
        icon: si-rss
        description: Latest headlines from rss_feeds.json
        widget:
          type: customapi
          url: "{{HOMEPAGE_VAR_STATUS_API}}/rss-digest"
          refreshInterval: 600000
          display: dynamic-list
          mappings:
            items: items
            name: name
            label: label
            limit: 6
```

- [ ] **Step 2: Merge Downloads into Infrastructure**

Move the whole `- JDownloader 2:` entry (keeping the `{{HOMEPAGE_VAR_JD_…}}` lines from Task 1) so it becomes the third card under `- Infrastructure:`, after FreshRSS. Delete the now-empty `- Downloads:` group line. Update the Infrastructure comment block's first line to:

```yaml
# Container list (Homepage, FreshRSS, JDownloader). Each card is bound to a
```

- [ ] **Step 3: Replace `settings.yaml`**

The whole file becomes the following. The `search:` block is dropped because it has no effect: settings.yaml has no `search` key, and the live search is the widget in widgets.yaml. `providers: status:` is dropped in favour of the real key, `statusStyle`.

```yaml
---
# For configuration options and examples, please see:
# https://gethomepage.dev/configs/settings/

title: CYBER://HUB
theme: dark
color: slate
headerStyle: boxed

# Soft glass: frosted cards, equal-height rows.
cardBlur: md
useEqualHeights: true
statusStyle: "dot"
showStats: true

# Every service group is a full-width row (Homepage styles are "row" or the
# default "column"; there is no "grid"). Key order here = order on the page.
layout:
  Hermes Agents:
    style: row
    columns: 4
  Mind:
    style: row
    columns: 3
  Infrastructure:
    style: row
    columns: 3
  YouTube:
    style: row
    columns: 3
    initiallyCollapsed: true
```

- [ ] **Step 4: Verify in the browser**

Homepage picks up config changes without a restart, but settings.yaml changes need its static page regenerated: click the refresh icon at the bottom right of the dashboard, then hard-refresh `http://localhost:3000`.

Run this in the page's devtools console (or the browser tool) at a desktop width to confirm every group is full width:

```js
[...document.querySelectorAll('.services-group')].map(g => [g.querySelector('.service-group-name')?.textContent, Math.round(g.getBoundingClientRect().width)])
```

Expected:
- Four groups, in the order Hermes Agents, Mind, Infrastructure, YouTube, each roughly the full content width. Before this change each was about 304px wide.
- Hermes Agents shows 4 cards in one row, Mind 3, and Infrastructure 3 (Homepage, FreshRSS, JDownloader). YouTube is collapsed; expanding it shows 2 rows of 3.
- Cards in each row are the same height. Status dots appear on the Infrastructure cards.
- At 375px width, every row stacks to one card per line with no horizontal scroll.
- Skills Learned shows 5 rows, and the "8 weeks" value is a sparkline string.
- Second Brain shows title / folder, the excerpt, and "Added this week".
- Clicking the note row opens that note in Obsidian.
- No card shows "API Error".

If the 140-character excerpt wraps to more than 3 lines in the Mind column, lower `EXCERPT_CHARS` in `second_brain.py` to `90`. Update `test_parse_note_truncates_long_excerpt` only if the constant name changes, since it already reads the constant. Then re-run `pytest -q` and restart the API as in Task 4 Step 7.

- [ ] **Step 5: Commit**

```bash
git add config/services.yaml config/settings.yaml status-api/second_brain.py
git commit -m "feat(dashboard): Mind group, balanced row layout, drop dead settings"
```

---

### Task 6: Soft glass `custom.css`

**Files:**
- Rewrite: `config/custom.css`

**Interfaces:**
- Consumes: Homepage semantic classes listed in Global Constraints; the Mind cards from Task 5 (for the visual check).
- Produces: final look.

- [ ] **Step 1: Replace `config/custom.css`**

```css
/* ---------------------------------------------------------------------------
   CYBER://HUB -- soft glass theme.
   Targets Homepage's semantic classes (.service-card, .service-block, ...)
   rather than Tailwind utility classes, which change between releases.
   --------------------------------------------------------------------------- */

@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap");

:root {
  --glass-fill: rgba(255, 255, 255, 0.06);
  --glass-fill-hover: rgba(255, 255, 255, 0.09);
  --glass-inset: rgba(255, 255, 255, 0.04);
  --glass-border: rgba(255, 255, 255, 0.10);
  --glass-border-hover: rgba(255, 255, 255, 0.18);
  --glass-shadow: 0 8px 32px rgba(4, 6, 20, 0.28);
  --text-strong: #eef0f7;
  --text-muted: #9aa3b8;
  --accent: #b8a6ff;
  --radius-card: 16px;
  --radius-inset: 10px;
}

/* Background: soft indigo -> slate -> teal wash */
html, body, #__next {
  background-color: #12141f !important;
}
body {
  background-image:
    radial-gradient(1200px 800px at 12% 8%, rgba(99, 102, 241, 0.26), transparent 60%),
    radial-gradient(1000px 700px at 88% 92%, rgba(45, 212, 191, 0.13), transparent 60%),
    linear-gradient(160deg, #171a2b 0%, #12141f 55%, #0f1a24 100%) !important;
  background-attachment: fixed !important;
}
body, #__next {
  font-family: "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  color: var(--text-strong);
}

/* Cards */
.service-card,
#information-widgets {
  background: var(--glass-fill) !important;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-card) !important;
  box-shadow: var(--glass-shadow) !important;
  backdrop-filter: blur(14px) saturate(140%);
  -webkit-backdrop-filter: blur(14px) saturate(140%);
}
.service-card {
  transition: transform 0.2s ease, border-color 0.2s ease, background 0.2s ease;
}
.service-card:hover {
  background: var(--glass-fill-hover) !important;
  border-color: var(--glass-border-hover);
  transform: translateY(-2px);
}
@media (prefers-reduced-motion: reduce) {
  .service-card, .service-card:hover { transition: none; transform: none; }
}

/* Inner stat blocks and list rows */
.service-block,
.service-container .rounded-sm {
  background: var(--glass-inset) !important;
  border-radius: var(--radius-inset) !important;
}

/* Values strong, labels muted: block = value then label; row = name then value */
.service-block > div:first-child { color: var(--text-strong); font-weight: 500; }
.service-block > div:last-child  { color: var(--text-muted); letter-spacing: 0.06em; }
.service-container .font-thin    { color: var(--text-muted); }
.service-container .font-bold    { color: var(--text-strong); font-weight: 500; }

/* Headings and text */
.service-group-name,
.bookmark-group-name {
  color: var(--text-strong) !important;
  font-size: 0.8rem !important;
  font-weight: 600 !important;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.service-name,
.service-title-text {
  color: var(--text-strong) !important;
  font-weight: 600;
}
.service-description {
  color: var(--text-muted) !important;
}

/* The one accent colour: hovered links */
.service-card a:hover,
.bookmark:hover .bookmark-name {
  color: var(--accent) !important;
}
```

- [ ] **Step 2: Visual check (desktop, then phone width)**

Hard-refresh `http://localhost:3000`. Check:
- The cards are translucent with rounded corners.
- No border-inside-border nesting.
- Group names are small uppercase headings.
- In every stat block the number is brighter than its label.
- Cron/Headlines/YouTube rows show the left name muted and the right value bright.
- A card lifts 2px on hover.

Then emulate a 375px-wide viewport. Expected: cards stack in one column, nothing scrolls horizontally, and the Second Brain excerpt wraps cleanly.

If the resources/search header bar looks double-framed (Homepage already styles `#information-widgets`), drop `#information-widgets` from the Cards selector and re-check.

- [ ] **Step 3: Commit**

```bash
git add config/custom.css
git commit -m "style(dashboard): soft glass theme"
```

---

## Rollback

- Config and code: `git revert <commit>` or `git checkout <commit> -- <file>` in `C:\Users\Admin\docker\homepage`. Homepage reloads config on its own. For status API changes, restart it as in Task 4 Step 7.
- Skills ledger: delete `status-api/state/skills_ledger.json` to re-seed from timestamps.
