"""Files card behind the /everything endpoint (voidtools Everything 1.5).

Two lists in one card:
  * Recent  -- the newest files in my own folders, by an include list
               (folders + file types) rather than an ever-growing exclude
               list, so app caches and logs never show up.
  * Cleanup -- Downloads files older than N days: a total, then the biggest.

Homepage's customapi widget calls this endpoint server-side with
`username`/`password`; the Basic auth header it sends is forwarded to
Everything as-is, so the credentials live only in Homepage's
HOMEPAGE_VAR_EVERYTHING_* env vars and are never stored here.

Everything returns size and date_modified as strings; date_modified is a
Windows FILETIME (100 ns ticks since 1601-01-01), converted with integer
maths because the raw value exceeds a double's exact range.
"""

from __future__ import annotations

import json
import ntpath
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

FILETIME_EPOCH_MS = 11644473600000
TIMEOUT_S = 8
RECENT_COUNT = 4
CLEANUP_TOP = 3
CLEANUP_SCAN = 20000   # rows summed for the cleanup total; more shows as "≥"
NAME_MAX = 28          # the card is narrow; longer names wrap onto several lines
FOLDER_MAX = 18
DEFAULT_OLDER_DAYS = 30

HOME = r"C:\Users\Admin"
DOWNLOADS = HOME + r"\Downloads"
# Not the second-brain vault: Hermes writes it every few minutes and the
# Second Brain card already covers it.
MY_FOLDERS = [HOME + "\\" + f for f in
              ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "OneDrive")]
MY_TYPES = ("pdf;doc;docx;xls;xlsx;csv;ppt;pptx;txt;md;epub;"
            "jpg;jpeg;png;gif;webp;heic;svg;mp4;mkv;mov;webm;mp3;flac;m4a;wav;"
            "zip;7z;rar;exe;msi")
# \Logs\: ShareX and several games log into Documents\<app>\Logs.
NOISE = r'!"\.git\" !"\.obsidian\" !"~$" !"\Logs\"'

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




def validate_url(url):
    parts = urllib.parse.urlsplit(url or "")
    if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError("url must be http(s) on localhost or host.docker.internal")
    return f"{parts.scheme}://{parts.netloc}"


def http_fetch(base, auth_header, query, count, sort=None):
    params = {"s": query, "j": "1", "c": str(count),
              "path_column": "1", "size_column": "1", "date_modified_column": "1"}
    if sort:
        params.update(sort=sort, ascending="0")
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


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def web_search(web, query, sort=None):
    """Link into Everything's own web UI (opened by the browser on this PC)."""
    url = f"{web}/?search={urllib.parse.quote(query, safe='')}"
    return url + (f"&sort={sort}&ascending=0" if sort else "")


def cutoff_date(now_ms, days):
    return (datetime.fromtimestamp(now_ms / 1000) - timedelta(days=days)).date().isoformat()


def file_queries(days, now_ms):
    folders = " | ".join(f'"{f}\\"' for f in MY_FOLDERS)
    old = f'file: "{DOWNLOADS}\\" dm:<{cutoff_date(now_ms, days)}'
    return {
        "recent": (f"file: <{folders}> ext:{MY_TYPES} {NOISE}", RECENT_COUNT, "date_modified"),
        "biggest": (old, CLEANUP_TOP, "size"),
        "total": (old, CLEANUP_SCAN, "size"),
    }


def _message(status, text):
    return {"status": status, "recent": [{"name": text, "label": "", "href": ""}],
            "cleanup": [], "cleanup_files": 0, "cleanup_bytes": 0}


def build_files_card(fetch, web, days, now_ms):
    """`fetch(query, count, sort=None)` returns Everything's JSON dict.
    `web` is Everything's web UI as the browser sees it (rows link there)."""
    queries = file_queries(days, now_ms)
    try:
        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            futs = {k: pool.submit(fetch, q, c, s) for k, (q, c, s) in queries.items()}
            res = {k: f.result() for k, f in futs.items()}
    except EverythingAuthError:
        return _message("auth", "Everything login failed")
    except EverythingOffline:
        return _message("offline", "Everything offline")

    def full_path(r):
        return ntpath.join(r.get("path") or "", r.get("name") or "")

    recent = []
    for r in (res["recent"].get("results") or [])[:RECENT_COUNT]:
        folder = truncate(ntpath.basename((r.get("path") or "").rstrip("\\")) or "—", FOLDER_MAX)
        recent.append({"name": truncate(r.get("name") or "?", NAME_MAX),
                       "label": f"{folder} · {ago(filetime_to_ms(r.get('date_modified')), now_ms)}",
                       "href": web_search(web, f'"{full_path(r)}"')})
    if not recent:
        recent = [{"name": "No recent files", "label": "", "href": ""}]

    scanned = res["total"].get("results") or []
    files = _count(res["total"])
    total = sum(_int(r.get("size")) for r in scanned)
    summary = {"name": f"Downloads > {days} days",
               "label": "all tidy" if not files else
               f"{'≥ ' if files > len(scanned) else ''}{human_size(total)} · {files:,} files",
               "href": web_search(web, queries["total"][0][len("file: "):], sort="size")}
    biggest = [{"name": truncate(r.get("name") or "?", NAME_MAX),
                "label": f"{human_size(r.get('size'))} · {ago(filetime_to_ms(r.get('date_modified')), now_ms)}",
                "href": web_search(web, f'"{full_path(r)}"')}
               for r in (res["biggest"].get("results") or [])[:CLEANUP_TOP]]

    return {"status": "ok", "recent": recent, "cleanup": [summary] + biggest,
            "cleanup_files": files, "cleanup_bytes": total, "cutoff": cutoff_date(now_ms, days)}
