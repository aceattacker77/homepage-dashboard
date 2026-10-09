#!/usr/bin/env python3
"""
Hermes status API -- read-only status surface for the Homepage dashboard.

Exposes JSON endpoints consumed by Homepage `customapi` widgets:
  /health              liveness probe
  /hermes-status       worker + builder agent online/offline, last activity
  /openrouter-credits  current OpenRouter balance
  /cron-status         Hermes cron jobs, next run, last run result
  /rss-digest          latest headlines from rss_feeds.json (no Telegram send)
  /gpu-status          host GPU metrics (bonus -- Homepage resources widget has no GPU)
  /skills-learned      new (non-bundled) Hermes skills per week
  /second-brain        note of the day + notes added this week from the vault
  /now-playing         MusicBee's current track (file written by musicbee-plugin/)
  /everything          Files card: recent files + Downloads cleanup via Everything (auth passed through)

STRICTLY READ-ONLY. It never creates, edits, pauses or fires a cron job, and
never sends messages. It only reads Hermes state files and the second-brain
vault, shells out to read-only commands (nvidia-smi, git log/ls-files), and
writes nothing but its own state/ (skills ledger, note of the day).

Run:  python status_api.py       (binds 0.0.0.0:8787)
"""

from __future__ import annotations

import concurrent.futures as futures
import ctypes
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import everything
import now_playing
import second_brain
import skills_learned

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

PORT = int(os.environ.get("HERMES_STATUS_PORT", "8787"))

HERMES_BASE = os.environ.get("HERMES_BASE", r"C:\Users\Admin\AppData\Local\hermes")
HERMES_PROFILES_DIR = os.path.join(HERMES_BASE, "profiles")

# The two agents this dashboard surfaces. "worker" is the default profile
# (owns the file-triage + Daily Digest cron jobs); "builder" is hermes-builder.
AGENTS = [
    {"key": "worker", "profile": "default", "home": HERMES_BASE, "role": "Worker"},
    {
        "key": "builder",
        "profile": "hermes-builder",
        "home": os.path.join(HERMES_PROFILES_DIR, "hermes-builder"),
        "role": "Builder",
    },
]

RSS_FEEDS_FILE = os.path.join(HERMES_BASE, "rss_feeds.json")
RSS_CACHE_TTL = 600        # seconds -- feeds are slow, cache the digest
CRON_CACHE_TTL = 30
OPENROUTER_CACHE_TTL = 60
GPU_CACHE_TTL = 5

USER_AGENT = "Mozilla/5.0 (compatible; HermesStatusAPI/1.0)"

# Skills Learned card. Names in hermes-agent's own trees are "bundled", not
# learned. The ledger lives in this API's own state/ dir, not Hermes'.
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
# Today's pick, remembered so new notes don't reshuffle it mid-day.
NOTE_OF_DAY_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "note_of_day.json")

# Now Playing card: written by the MusicBee plugin in ../musicbee-plugin.
NOW_PLAYING_FILE = os.environ.get(
    "MUSICBEE_NOW_PLAYING",
    os.path.join(os.environ.get("APPDATA", r"C:\Users\Admin\AppData\Roaming"),
                 "MusicBee", "HomepageNowPlaying", "nowplaying.json"))
NOW_PLAYING_CACHE_TTL = 2

# Files card: queries Everything's HTTP server; credentials arrive on each
# request from Homepage (customapi username/password) and are only forwarded.
# EVERYTHING_WEB is the same server as the user's browser reaches it (rows
# link there).
EVERYTHING_URL = os.environ.get("EVERYTHING_URL", "http://127.0.0.1:8089")
EVERYTHING_WEB = os.environ.get("EVERYTHING_WEB", "http://localhost:8089")
EVERYTHING_CACHE_TTL = 60


def skill_trees():
    """Base skills plus every profile's, re-globbed so new profiles appear."""
    return [os.path.join(HERMES_BASE, "skills")] + sorted(
        glob.glob(os.path.join(HERMES_PROFILES_DIR, "*", "skills")))

# Must match the category_map in scripts/fetch_and_summarize.py so the widget
# reads the same way as the 18:00 Telegram digest.
CATEGORY_MAP = {
    "tech": "Tech / AI",
    "world_news": "World News",
    "business": "Business",
    "gaming": "Gaming",
    "soccer_epl": "Soccer — EPL",
    "gaming_hardware": "Gaming Hardware",
}

app = FastAPI(title="Hermes Status API", version="1.0.0")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _cache():
    """Per-endpoint {value, expires} store guarded by a lock."""
    return {"value": None, "expires": 0.0, "lock": threading.Lock()}


_CACHES = {name: _cache() for name in ("cron", "rss", "credits", "gpu", "skills", "brain", "nowplaying")}


def cached(name, ttl, producer):
    c = _CACHES[name]
    now = time.time()
    if c["value"] is not None and now < c["expires"]:
        return c["value"]
    with c["lock"]:
        now = time.time()
        if c["value"] is not None and now < c["expires"]:
            return c["value"]
        try:
            c["value"] = producer()
            c["expires"] = time.time() + ttl
        except Exception as exc:  # keep serving the last good value
            if c["value"] is None:
                raise
            c["value"].setdefault("cache_warning", f"{type(exc).__name__}: {exc}")
            c["expires"] = time.time() + min(ttl, 30)
        return c["value"]


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return default


def read_env_key(path, key):
    """Minimal .env reader -- returns None when absent/commented."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    v = v.strip().strip('"').strip("'")
                    if v:
                        return v
    except Exception:
        pass
    return None


def openrouter_key():
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"].strip()
    # Profile .env first (hermes-builder holds the live key), then base .env.
    for home in (os.path.join(HERMES_PROFILES_DIR, "hermes-builder"), HERMES_BASE):
        key = read_env_key(os.path.join(home, ".env"), "OPENROUTER_API_KEY")
        if key:
            return key
    return None


def now_utc():
    return datetime.now(timezone.utc)


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def humanise_delta(seconds):
    """Compact '2h ago' / 'in 3d' style label."""
    if seconds is None:
        return "unknown"
    past = seconds >= 0
    s = abs(int(seconds))
    for limit, div, unit in ((60, 1, "s"), (3600, 60, "m"), (86400, 3600, "h"), (None, 86400, "d")):
        if limit is None or s < limit:
            value = max(1, round(s / div)) if div > 1 else s
            return f"{value}{unit} ago" if past else f"in {value}{unit}"
    return "unknown"


def ago_label(iso_value):
    dt = parse_iso(iso_value)
    if not dt:
        return "never"
    return humanise_delta((now_utc() - dt).total_seconds())


def in_label(iso_value):
    dt = parse_iso(iso_value)
    if not dt:
        return "—"
    return humanise_delta((now_utc() - dt).total_seconds()).replace(" ago", " ago")


# --------------------------------------------------------------------------
# Process liveness (never os.kill on Windows -- it TERMINATES the process)
# --------------------------------------------------------------------------

_STILL_ACTIVE = 259


def pid_alive(pid):
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def profile_model(home):
    """Read the active model/provider out of config.yaml (model.default)."""
    try:
        import yaml  # available in the Hermes venv
        with open(os.path.join(home, "config.yaml"), "r", encoding="utf-8-sig") as fh:
            cfg = yaml.safe_load(fh) or {}
        model = cfg.get("model") or {}
        if isinstance(model, dict):
            return model.get("default") or model.get("name") or model.get("model"), model.get("provider")
        if isinstance(model, str):
            return model, None
    except Exception:
        pass
    return None, None


def newest_mtime(paths):
    newest = 0.0
    for path in paths:
        try:
            newest = max(newest, os.path.getmtime(path))
        except OSError:
            continue
    return newest


def session_activity(home):
    """Last real agent activity, from the canonical session store.

    `sessions.last_activity_at` is written when an agent actually does work, so
    this is meaningful -- unlike the cron ticker heartbeat, which fires
    constantly and would peg every agent at '1s ago'.
    """
    import sqlite3

    out = {
        "last_activity": None,
        "last_activity_age_seconds": None,
        "last_activity_source": None,
        "last_activity_title": None,
        "last_activity_detail": None,
        "session_count": 0,
    }
    path = os.path.join(home, "state.db")
    if os.path.exists(path):
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=4)
            con.row_factory = sqlite3.Row
            out["session_count"] = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            row = con.execute(
                "SELECT source, title, model, last_activity_at, last_activity_description "
                "FROM sessions WHERE last_activity_at IS NOT NULL "
                "ORDER BY last_activity_at DESC LIMIT 1"
            ).fetchone()
            if row and row["last_activity_at"]:
                dt = datetime.fromtimestamp(row["last_activity_at"], tz=timezone.utc)
                out["last_activity"] = dt.isoformat()
                out["last_activity_age_seconds"] = (now_utc() - dt).total_seconds()
                out["last_activity_source"] = row["source"]
                out["last_activity_title"] = row["title"]
                out["last_activity_detail"] = (row["last_activity_description"] or "").strip() or None
            con.close()
        except Exception as exc:
            out["activity_error"] = f"{type(exc).__name__}: {exc}"

    if not out["last_activity"]:
        # Fallback: newest session transcript / store file on disk.
        newest = newest_mtime([
            os.path.join(home, "state.db"),
            os.path.join(home, "state.db-wal"),
        ])
        try:
            for entry in os.scandir(os.path.join(home, "sessions")):
                try:
                    newest = max(newest, entry.stat().st_mtime)
                except OSError:
                    continue
        except OSError:
            pass
        if newest > 0:
            dt = datetime.fromtimestamp(newest, tz=timezone.utc)
            out["last_activity"] = dt.isoformat()
            out["last_activity_age_seconds"] = (now_utc() - dt).total_seconds()
            out["last_activity_source"] = "filesystem"
    return out


def gateway_info(home):
    state = read_json(os.path.join(home, "gateway_state.json"), {}) or {}
    pid_file = read_json(os.path.join(home, "gateway.pid"), {}) or {}
    pid = state.get("pid") or pid_file.get("pid")
    alive = pid_alive(pid)
    platforms = state.get("platforms") or {}
    return {
        "pid": pid,
        "pid_alive": alive,
        "gateway_state": state.get("gateway_state") or "unknown",
        "online": bool(alive and state.get("gateway_state") == "running"),
        "platforms": platforms,
        "telegram": (platforms.get("telegram") or {}).get("state"),
        "version": state.get("code_version"),
        "updated_at": state.get("updated_at"),
    }





# --------------------------------------------------------------------------
# 1. /hermes-status
# --------------------------------------------------------------------------

def build_hermes_status():
    agents = {}
    for spec in AGENTS:
        home = spec["home"]
        gw = gateway_info(home)
        activity = session_activity(home)
        model, provider = profile_model(home)
        jobs = read_json(os.path.join(home, "cron", "jobs.json"), {}) or {}
        age = activity["last_activity_age_seconds"]
        agents[spec["key"]] = {
            "profile": spec["profile"],
            "role": spec["role"],
            "online": gw["online"],
            "status": "Online" if gw["online"] else "Offline",
            "pid": gw["pid"],
            "gateway_state": gw["gateway_state"],
            "model": model,
            "provider": provider,
            "telegram": gw["telegram"],
            "version": gw["version"],
            "cron_jobs": len(jobs.get("jobs") or []),
            "session_count": activity["session_count"],
            "last_activity": activity["last_activity"],
            "last_activity_ago": humanise_delta(age) if age is not None else "unknown",
            "last_activity_age_seconds": age,
            "last_activity_source": activity["last_activity_source"],
            "last_activity_title": activity["last_activity_title"],
            "activity_label": (
                f"{humanise_delta(age)} · {activity['last_activity_source']}"
                if age is not None and activity["last_activity_source"]
                else "unknown"
            ),
        }

    online = sum(1 for a in agents.values() if a["online"])
    worker, builder = agents["worker"], agents["builder"]
    ages = [(a["last_activity_age_seconds"], a["last_activity"]) for a in agents.values()
            if a["last_activity_age_seconds"] is not None]
    newest_age, newest_iso = min(ages, key=lambda pair: pair[0]) if ages else (None, None)

    return {
        "generated_at": now_utc().isoformat(),
        "agents": agents,
        # Flat, widget-friendly aliases (Homepage block view reads flat paths).
        "worker_status": worker["status"],
        "worker_model": worker["model"] or "unknown",
        "worker_last_activity": worker["last_activity"],
        "worker_last_activity_ago": worker["last_activity_ago"],
        "worker_activity_label": worker["activity_label"],
        "worker_summary": f"{worker['status']} · {worker['last_activity_ago']}",
        "builder_status": builder["status"],
        "builder_model": builder["model"] or "unknown",
        "builder_last_activity": builder["last_activity"],
        "builder_last_activity_ago": builder["last_activity_ago"],
        "builder_activity_label": builder["activity_label"],
        "builder_summary": f"{builder['status']} · {builder['last_activity_ago']}",
        "agents_online": f"{online}/{len(agents)}",
        "agents_online_count": online,
        "agents_total": len(agents),
        "last_activity": newest_iso,
        "last_activity_ago": humanise_delta(newest_age) if newest_age is not None else "unknown",
    }


@app.get("/hermes-status")
def hermes_status():
    return JSONResponse(build_hermes_status())


# --------------------------------------------------------------------------
# 2. /openrouter-credits
# --------------------------------------------------------------------------

def build_credits():
    key = openrouter_key()
    if not key:
        return {"status": "error", "error": "OPENROUTER_API_KEY not found",
                "remaining_label": "no key", "used_percent_label": "—"}

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/credits",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                 "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    data = payload.get("data") or payload
    total = float(data.get("total_credits") or 0)
    used = float(data.get("total_usage") or 0)
    remaining = total - used
    pct = (used / total * 100.0) if total > 0 else 0.0

    return {
        "status": "ok",
        "total_credits": round(total, 4),
        "total_usage": round(used, 4),
        "remaining": round(remaining, 4),
        "used_percent": round(pct, 2),
        "used_percent_label": f"{pct:.1f}%",
        "total_credits_label": f"${total:.2f}",
        "used_label": f"${used:.2f}",
        "remaining_label": f"${remaining:.2f}",
        "generated_at": now_utc().isoformat(),
    }


@app.get("/openrouter-credits")
def openrouter_credits():
    try:
        return JSONResponse(cached("credits", OPENROUTER_CACHE_TTL, build_credits))
    except Exception as exc:
        return JSONResponse({"status": "error", "error": f"{type(exc).__name__}: {exc}",
                             "remaining_label": "unavailable", "used_percent_label": "—"})


# --------------------------------------------------------------------------
# 3. /cron-status
# --------------------------------------------------------------------------

def executions_index(home):
    """Map job_id -> latest execution row, if the executions DB is readable."""
    import sqlite3
    path = os.path.join(home, "cron", "executions.db")
    out = {}
    if not os.path.exists(path):
        return out
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        cols = {r[1] for r in con.execute("PRAGMA table_info(executions)")}
        order = "started_at" if "started_at" in cols else ("created_at" if "created_at" in cols else "rowid")
        rows = con.execute(
            f"SELECT * FROM executions ORDER BY {order} DESC LIMIT 200"
        ).fetchall()
        for row in rows:
            d = dict(row)
            jid = d.get("job_id")
            if jid and jid not in out:
                out[jid] = d
        con.close()
    except Exception:
        pass
    return out


def short_job_name(name):
    """Cron job names are often whole prompts -- keep them readable in a widget."""
    n = re.sub(r"\s+", " ", (name or "").strip())
    cleaned = re.sub(r"[A-Za-z]:\\[^\s]*", "", n)          # drop Windows paths
    cleaned = re.sub(r"\band\b\s*$", "", cleaned).strip(" ,;:-")
    if len(cleaned.split()) >= 2 or len(cleaned) >= 8:      # only if still useful
        n = cleaned
    if len(n) > 30:
        n = n[:29].rstrip() + "…"
    return n or "(unnamed)"


def build_cron_status():
    home = HERMES_BASE  # the worker profile owns the scheduled jobs
    payload = read_json(os.path.join(home, "cron", "jobs.json"), {}) or {}
    raw_jobs = payload.get("jobs") or []
    execs = executions_index(home)

    jobs = []
    for job in raw_jobs:
        next_run = job.get("next_run_at")
        last_run = job.get("last_run_at")
        status = job.get("last_status") or "never"
        enabled = bool(job.get("enabled"))
        state = job.get("state") or ("paused" if not enabled else "scheduled")
        nxt = in_label(next_run) if next_run else "—"
        exec_row = execs.get(job.get("id")) or {}
        jobs.append({
            "id": job.get("id"),
            "name": short_job_name(job.get("name")),
            "full_name": job.get("name") or "(unnamed)",
            "schedule": job.get("schedule_display") or "—",
            "enabled": enabled,
            "state": state if enabled else "disabled",
            "deliver": job.get("deliver") or "—",
            "next_run": next_run,
            "next_run_in": nxt,
            "last_run": last_run,
            "last_run_ago": ago_label(last_run),
            "last_status": status,
            "last_error": job.get("last_error"),
            "failure_streak": job.get("failure_streak") or 0,
            "execution_state": exec_row.get("state") or exec_row.get("status"),
            # Single-line label for Homepage dynamic-list
            "summary": f"{nxt} · {status}",
        })

    # Soonest upcoming job first
    jobs.sort(key=lambda j: (j["next_run"] is None, j["next_run"] or ""))

    ok_count = sum(1 for j in jobs if j["last_status"] == "ok")
    nxt_job = jobs[0] if jobs else None
    return {
        "generated_at": now_utc().isoformat(),
        "source": os.path.join(home, "cron", "jobs.json"),
        "job_count": len(jobs),
        "active_count": sum(1 for j in jobs if j["enabled"]),
        "healthy_count": ok_count,
        "jobs": jobs,
        "items": jobs,  # alias for Homepage dynamic-list
        "next_job": nxt_job["name"] if nxt_job else "—",
        "next_run": nxt_job["next_run"] if nxt_job else None,
        "next_run_in": nxt_job["next_run_in"] if nxt_job else "—",
        "last_status": nxt_job["last_status"] if nxt_job else "—",
        "job_count_label": f"{len(jobs)} jobs",
        "healthy_label": f"{ok_count}/{len(jobs)} ok",
    }


@app.get("/cron-status")
def cron_status():
    try:
        return JSONResponse(cached("cron", CRON_CACHE_TTL, build_cron_status))
    except Exception as exc:
        return JSONResponse({"status": "error", "error": f"{type(exc).__name__}: {exc}",
                             "job_count": 0, "jobs": [], "items": [],
                             "next_job": "unavailable", "next_run_in": "—",
                             "next_run": None, "last_status": "—"})


# --------------------------------------------------------------------------
# 4. /rss-digest
# --------------------------------------------------------------------------

def strip_tag(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def text_of(node, *names):
    for child in node:
        if strip_tag(child.tag) in names:
            value = (child.text or "").strip()
            if value:
                return value
    return None


def link_of(node):
    for child in node:
        if strip_tag(child.tag) != "link":
            continue
        href = child.get("href")
        if href:                       # Atom
            return href.strip()
        value = (child.text or "").strip()
        if value:                      # RSS
            return value
    return None


def parse_date(value):
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)  # RFC-822 (RSS)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value[:len(fmt) + 6] if "%z" in fmt else value, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def fetch_feed(feed, max_items=6, window_hours=48):
    """Fetch one feed and return recent items (no LLM summarisation)."""
    category = feed.get("category") or "uncategorised"
    source = feed.get("name") or feed.get("url")
    req = urllib.request.Request(feed["url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read()

    root = ET.fromstring(body)
    nodes = [n for n in root.iter() if strip_tag(n.tag) in ("item", "entry")]
    cutoff = now_utc() - timedelta(hours=window_hours)

    items = []
    for node in nodes[:25]:
        title = text_of(node, "title") or "(untitled)"
        published = text_of(node, "pubDate", "published", "updated", "date")
        dt = parse_date(published)
        items.append({
            "title": re.sub(r"\s+", " ", title).strip(),
            "source": source,
            "category": CATEGORY_MAP.get(category, category.replace("_", " ").title()),
            "category_key": category,
            "link": link_of(node) or feed["url"],
            "published": dt.isoformat() if dt else None,
            "published_ts": dt.timestamp() if dt else 0.0,
            "published_ago": humanise_delta((now_utc() - dt).total_seconds()) if dt else "undated",
        })

    recent = [i for i in items if i["published_ts"] >= cutoff.timestamp()]
    # Fall back to the newest handful when a feed publishes no parsable dates.
    if not recent:
        recent = items[:3]
    recent.sort(key=lambda i: i["published_ts"], reverse=True)
    return recent[:max_items]


def build_rss_digest():
    feeds_by_cat = read_json(RSS_FEEDS_FILE, {}) or {}
    flat = [(cat, feed) for cat, entries in feeds_by_cat.items() if isinstance(entries, list)
            for feed in entries]
    if not flat:
        return {"status": "error", "error": f"no feeds in {RSS_FEEDS_FILE}",
                "item_count": 0, "items": [], "headline_count": 0}

    collected, errors = [], []
    with futures.ThreadPoolExecutor(max_workers=8) as pool:
        submitted = {pool.submit(fetch_feed, feed): (cat, feed) for cat, feed in flat}
        for fut in futures.as_completed(submitted, timeout=45):
            cat, feed = submitted[fut]
            try:
                collected.extend(fut.result())
            except Exception as exc:
                errors.append(f"{feed.get('name')}: {type(exc).__name__}")

    collected.sort(key=lambda i: i["published_ts"], reverse=True)
    for item in collected:
        item["label"] = f"{item['category']} · {item['published_ago']}"
        item["name"] = item["title"]

    categories = []
    for item in collected:
        if item["category"] not in categories:
            categories.append(item["category"])

    return {
        "status": "ok",
        "generated_at": now_utc().isoformat(),
        "source": RSS_FEEDS_FILE,
        "feed_count": len(flat),
        "failed_feeds": errors,
        "item_count": len(collected),
        "headline_count": len(collected),
        "headline_count_label": f"{len(collected)} headlines",
        "feed_count_label": f"{len(flat) - len(errors)}/{len(flat)} feeds",
        "categories": categories,
        "latest_headline": collected[0]["title"] if collected else "none",
        "latest_headline_ago": collected[0]["published_ago"] if collected else "—",
        "latest_headline_link": collected[0]["link"] if collected else "",
        "items": collected,
    }


@app.get("/rss-digest")
def rss_digest():
    try:
        return JSONResponse(cached("rss", RSS_CACHE_TTL, build_rss_digest))
    except Exception as exc:
        return JSONResponse({"status": "error", "error": f"{type(exc).__name__}: {exc}",
                             "item_count": 0, "items": [], "headline_count": 0,
                             "headline_count_label": "unavailable", "feed_count_label": "—",
                             "latest_headline": "unavailable", "latest_headline_ago": "—"})


# --------------------------------------------------------------------------
# 5. /youtube-feeds
#
# Homepage has NO native RSS/YouTube widget -- confirmed against
# src/widgets/ and src/components/widgets/ at both v2.3.0 and dev, where the
# only rss-ish entry is "freshrss". So per-channel uploads are surfaced
# through the same Custom API widget pattern as the Hermes cards.
#
# Dashboard-only: this reads youtube_channels.json and YouTube's public feed.
# It does NOT touch rss_feeds.json and plays no part in the digest pipeline.
# --------------------------------------------------------------------------

YOUTUBE_CHANNELS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "youtube_channels.json"
)
YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id="
YOUTUBE_CACHE_TTL = 600


def load_youtube_channels():
    data = read_json(YOUTUBE_CHANNELS_FILE, {}) or {}
    return data.get("channels") or []


def yt_stat(entry, tag, attr):
    for node in entry.iter():
        if strip_tag(node.tag) == tag:
            value = node.get(attr)
            if value:
                return value
    return None


def yt_views(entry):
    raw = yt_stat(entry, "statistics", "views")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def fetch_youtube_channel(channel, limit=8):
    """Return (channel_name_from_youtube, [video dicts])."""
    req = urllib.request.Request(
        YT_FEED + channel["channel_id"], headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read()

    root = ET.fromstring(body)
    feed_title = text_of(root, "title") or channel.get("name") or "?"

    videos = []
    for entry in [n for n in root.iter() if strip_tag(n.tag) == "entry"][:limit]:
        vid = text_of(entry, "videoId") or ""
        title = re.sub(r"\s+", " ", text_of(entry, "title") or "(untitled)").strip()
        dt = parse_date(text_of(entry, "published") or text_of(entry, "updated"))
        views = yt_views(entry)
        ago = humanise_delta((now_utc() - dt).total_seconds()) if dt else "unknown"
        views_label = f"{views:,} views" if views is not None else ""
        videos.append({
            "video_id": vid,
            "title": title,
            "name": title,
            "published": dt.isoformat() if dt else None,
            "published_ago": ago,
            "views": views,
            "views_label": views_label,
            "thumbnail": yt_stat(entry, "thumbnail", "url"),
            "link": f"https://www.youtube.com/watch?v={vid}" if vid else None,
            "label": f"{ago} · {views_label}" if views_label else ago,
        })
    return feed_title, videos


def build_youtube_feed(key):
    channels = load_youtube_channels()
    if not channels:
        return {"status": "error", "error": f"no channels in {YOUTUBE_CHANNELS_FILE}"}

    channel = next((c for c in channels if c.get("key") == key), None) or channels[0]
    feed_title, videos = fetch_youtube_channel(channel)
    latest = videos[0] if videos else None
    expected = (channel.get("name") or "").strip()

    return {
        "status": "ok",
        "generated_at": now_utc().isoformat(),
        # channel is the name YouTube itself reports -- the mix-up check.
        "channel": feed_title.strip(),
        "expected_name": expected,
        "name_matches": feed_title.strip() == expected,
        "handle": channel.get("handle"),
        "channel_id": channel["channel_id"],
        "video_count": len(videos),
        "video_count_label": f"{len(videos)} uploads",
        "latest_title": latest["title"] if latest else "no uploads",
        "latest_ago": latest["published_ago"] if latest else "—",
        "latest_views": latest["views_label"] if latest else "",
        "latest_video_id": latest["video_id"] if latest else "",
        "videos": videos,
        "items": videos,
    }


def yt_cache_name(key):
    name = f"youtube:{key or 'default'}"
    if name not in _CACHES:
        _CACHES[name] = _cache()
    return name


@app.get("/youtube-feeds")
def youtube_feeds(channel: str = ""):
    try:
        return JSONResponse(cached(yt_cache_name(channel), YOUTUBE_CACHE_TTL,
                                   lambda: build_youtube_feed(channel)))
    except Exception as exc:
        return JSONResponse({"status": "error", "error": f"{type(exc).__name__}: {exc}",
                             "channel": "unavailable", "video_count": 0,
                             "video_count_label": "unavailable",
                             "latest_title": "unavailable", "latest_ago": "—",
                             "latest_views": "", "items": [], "videos": []})


@app.get("/youtube-channels")
def youtube_channels():
    return JSONResponse({"channels": load_youtube_channels()})


# --------------------------------------------------------------------------
# 6. /gpu-status
# --------------------------------------------------------------------------

NVIDIA_QUERY = (
    "name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit"
)


def find_nvidia_smi():
    for candidate in ("nvidia-smi", r"C:\Windows\System32\nvidia-smi.exe",
                      r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
        try:
            subprocess.run([candidate, "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, timeout=10, check=False)
            return candidate
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            continue
    return None


def build_gpu_status():
    smi = find_nvidia_smi()
    if not smi:
        return {"status": "unavailable", "available": False, "label": "no GPU",
                "name": "nvidia-smi not found", "detail": "nvidia-smi not found on PATH"}

    proc = subprocess.run(
        [smi, f"--query-gpu={NVIDIA_QUERY}", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"status": "error", "available": False, "label": "error",
                "name": "nvidia-smi failed", "detail": (proc.stderr or "").strip()[:200]}

    out = {}
    for index, line in enumerate(proc.stdout.strip().splitlines()):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            continue
        def number(raw):
            try:
                return float(raw)
            except ValueError:
                return None
        used, total = number(parts[2]), number(parts[3])
        used_pct = (used / total * 100.0) if (used is not None and total) else None
        out = {
            "status": "ok",
            "available": True,
            "index": index,
            "name": parts[0],
            "utilization_percent": number(parts[1]),
            "memory_used_mb": used,
            "memory_total_mb": total,
            "memory_used_percent": round(used_pct, 1) if used_pct is not None else None,
            "temperature_c": number(parts[4]),
            "power_w": number(parts[5]),
            "power_limit_w": number(parts[6]),
            "vram_label": (f"{used / 1024:.1f} / {total / 1024:.1f} GB"
                           if used is not None and total else "—"),
            "utilization_label": (f"{number(parts[1]):.0f}%" if number(parts[1]) is not None else "—"),
            "temperature_label": (f"{number(parts[4]):.0f}°C" if number(parts[4]) is not None else "—"),
            "power_label": (f"{number(parts[5]):.0f} W" if number(parts[5]) is not None else "—"),
            "label": parts[0],
            "gpu_count": index + 1,
        }
        break

    out.setdefault("generated_at", now_utc().isoformat())
    return out


@app.get("/gpu-status")
def gpu_status():
    try:
        return JSONResponse(cached("gpu", GPU_CACHE_TTL, build_gpu_status))
    except Exception as exc:
        return JSONResponse({"status": "error", "available": False, "label": "error",
                             "name": f"{type(exc).__name__}: {exc}"})


# --------------------------------------------------------------------------
# 7. /skills-learned
# --------------------------------------------------------------------------

def build_skills_card():
    try:
        return skills_learned.build_skills_learned(
            skill_trees(), BUNDLED_SKILL_TREES, SKILLS_LEDGER, datetime.now().date())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Keep the card rendering (zeros + reason) instead of a 500.
        empty = skills_learned.summarise({"version": 1, "skills": {}}, datetime.now().date())
        return {**empty, "error": f"{type(exc).__name__}: {exc}"}


@app.get("/skills-learned")
def skills_learned_route():
    return JSONResponse(cached("skills", SKILLS_CACHE_TTL, build_skills_card))


# --------------------------------------------------------------------------
# 8. /second-brain
# --------------------------------------------------------------------------

def build_second_brain_card():
    try:
        return second_brain.build_second_brain(
            SECOND_BRAIN_DIR, SECOND_BRAIN_VAULT, datetime.now().astimezone(), NOTE_OF_DAY_STATE)
    except (OSError, ValueError) as exc:
        # Keep the card rendering (with the reason) instead of a 500.
        return {"error": f"{type(exc).__name__}: {exc}",
                "items": [{"name": "Vault unavailable", "label": str(exc), "href": ""}]}


@app.get("/second-brain")
def second_brain_route():
    return JSONResponse(cached("brain", SECOND_BRAIN_CACHE_TTL, build_second_brain_card))


# --------------------------------------------------------------------------
# 9. /now-playing
# --------------------------------------------------------------------------

@app.get("/now-playing")
def now_playing_route():
    return JSONResponse(cached("nowplaying", NOW_PLAYING_CACHE_TTL,
                               lambda: now_playing.build_now_playing(NOW_PLAYING_FILE, now_utc())))


# --------------------------------------------------------------------------
# 10. /everything
# --------------------------------------------------------------------------

@app.get("/everything")
def everything_route(request: Request, url: str = "", web: str = "",
                     days: int = everything.DEFAULT_OLDER_DAYS):
    try:
        base = everything.validate_url(url or EVERYTHING_URL)
        web_base = everything.validate_url(web or EVERYTHING_WEB)
    except ValueError as exc:
        return JSONResponse({"status": "error", "error": str(exc), "recent": [], "cleanup": []})
    days = min(max(days, 1), 3650)
    auth = request.headers.get("authorization")
    # Cache per config + credentials so a wrong password is never served a hit.
    name = "everything:" + str(hash((base, web_base, auth, days)))
    if name not in _CACHES:
        _CACHES[name] = _cache()
    fetch = lambda q, c, sort=None: everything.http_fetch(base, auth, q, c, sort)
    return JSONResponse(cached(name, EVERYTHING_CACHE_TTL, lambda: everything.build_files_card(
        fetch, web_base, days, int(time.time() * 1000))))


# --------------------------------------------------------------------------
# 6. /health
# --------------------------------------------------------------------------

@app.get("/health")
def health():
    return JSONResponse({
        "status": "ok",
        "service": "hermes-status-api",
        "port": PORT,
        "hermes_base": HERMES_BASE,
        "read_only": True,
        "time": now_utc().isoformat(),
    })


if __name__ == "__main__":
    import uvicorn
    print(f"Hermes status API -> http://0.0.0.0:{PORT}  (HERMES_BASE={HERMES_BASE})")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")