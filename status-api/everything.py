"""Everything card behind the /everything endpoint.

Queries voidtools Everything 1.5's HTTP server (JSON mode) for four counts and
the most recently modified files. Homepage's customapi widget calls this
endpoint server-side with `username`/`password`; the Basic auth header it
sends is forwarded to Everything as-is, so the credentials live only in
Homepage's HOMEPAGE_VAR_EVERYTHING_* env vars and are never stored here.

Everything returns size and date_modified as strings; date_modified is a
Windows FILETIME (100 ns ticks since 1601-01-01), converted with integer
maths because the raw value exceeds a double's exact range.
"""

from __future__ import annotations

import json
import ntpath
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

FILETIME_EPOCH_MS = 11644473600000
TIMEOUT_S = 8
RECENT_COUNT = 5
NAME_MAX = 28      # the card is narrow; longer names wrap onto several lines
FOLDER_MAX = 18

DEFAULT_EXCLUDES = [
    r'"C:\Users\Admin\AppData\"',
    r'"C:\ProgramData\"',
    r'"C:\Windows\"',
    '"$Recycle.Bin"',
    r'"\.git\"',
    r'"C:\Users\Admin\.claude\"',
    r'"C:\Program Files (x86)\Steam\appcache\"',
]
DEFAULT_HUGE = "2gb"
DOWNLOADS = r'"C:\Users\Admin\Downloads\"'

# Only ever talk to Everything on this machine: the status API listens on
# 0.0.0.0 and must not become a proxy to arbitrary hosts.
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


class EverythingOffline(Exception):
    pass


class EverythingAuthError(Exception):
    pass


def filetime_to_ms(value):
    """FILETIME string/int -> unix epoch milliseconds, or None."""
    try:
        return int(value) // 10000 - FILETIME_EPOCH_MS
    except (TypeError, ValueError):
        return None


def truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def human_size(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "—"


def ago(ms, now_ms):
    if ms is None:
        return "—"
    s = max(0, (now_ms - ms) // 1000)
    for limit, div, unit in ((60, 1, "s"), (3600, 60, "m"), (86400, 3600, "h"), (None, 86400, "d")):
        if limit is None or s < limit:
            return f"{s // div}{unit} ago"


def parse_excludes(raw):
    """`exclude` query value: entries separated by ';' or newlines, or the defaults."""
    if raw is None:
        return list(DEFAULT_EXCLUDES)
    items = [x.strip() for x in re.split(r"[;\n]", raw) if x.strip()]
    return [x if x.startswith('"') else f'"{x}"' for x in items]


def exclusion_clause(excludes):
    return " ".join(f"!{x.lstrip('!')}" for x in excludes)


def validate_url(url):
    parts = urllib.parse.urlsplit(url or "")
    if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError("url must be http(s) on localhost or host.docker.internal")
    return f"{parts.scheme}://{parts.netloc}"


def http_fetch(base, auth_header, query, count, sort=False):
    params = {"s": query, "j": "1", "c": str(count),
              "path_column": "1", "size_column": "1", "date_modified_column": "1"}
    if sort:
        params.update(sort="date_modified", ascending="0")
    req = urllib.request.Request(f"{base}/?{urllib.parse.urlencode(params)}")
    if auth_header:
        req.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8-sig"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise EverythingAuthError() from exc
        raise EverythingOffline(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise EverythingOffline(str(exc)) from exc


def _count(data):
    try:
        return int(data.get("totalResults") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _stat_card(status, label, **counts):
    keys = ("indexed", "changed_today", "huge", "downloads")
    out = {"status": status, "status_label": label, "items": []}
    for k in keys:
        v = counts.get(k)
        out[k] = v
        out[f"{k}_label"] = f"{v:,}" if isinstance(v, int) else label
    return out


def build_everything(fetch, excludes, huge, now_ms):
    """`fetch(query, count, sort=False)` returns Everything's JSON dict."""
    ex = exclusion_clause(excludes)
    queries = {
        "indexed": ("", 1, False),
        "changed_today": (f"file: dm:today {ex}".strip(), 1, False),
        "huge": (f"file: size:>{huge}", 1, False),
        "downloads": (f"file: {DOWNLOADS}", 1, False),
        "recent": (f"file: {ex}".strip(), RECENT_COUNT, True),
    }
    try:
        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            futs = {k: pool.submit(fetch, q, c, sort) for k, (q, c, sort) in queries.items()}
            results = {k: f.result() for k, f in futs.items()}
    except EverythingAuthError:
        return _stat_card("auth", "auth failed")
    except EverythingOffline:
        return _stat_card("offline", "offline")

    items = []
    for r in (results["recent"].get("results") or [])[:RECENT_COUNT]:
        ms = filetime_to_ms(r.get("date_modified"))
        folder = ntpath.basename((r.get("path") or "").rstrip("\\")) or r.get("path") or "—"
        rel = ago(ms, now_ms)
        size = human_size(r.get("size"))
        folder = truncate(folder, FOLDER_MAX)
        items.append({"name": truncate(r.get("name") or "?", NAME_MAX), "folder": folder, "path": r.get("path"),
                      "ago": rel, "size": size, "modified_ms": ms,
                      "label": f"{folder} · {rel} · {size}"})

    card = _stat_card("ok", "online", **{k: _count(results[k]) for k in
                                          ("indexed", "changed_today", "huge", "downloads")})
    card["items"] = items
    card["huge_threshold"] = huge
    return card
