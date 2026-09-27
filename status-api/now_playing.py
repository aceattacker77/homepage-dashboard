"""Now-playing card behind the /now-playing endpoint.

The MusicBee plugin in ../musicbee-plugin writes nowplaying.json on every
track or play-state change and every few seconds as a heartbeat. This module
only reads that file. While playing, the position is extrapolated from the
heartbeat time so the progress keeps moving between writes; a heartbeat older
than STALE_AFTER_S means MusicBee is no longer running.
"""

from __future__ import annotations

import json
from datetime import datetime

STALE_AFTER_S = 20

STATE_LABELS = {
    "playing": "▶ Playing",
    "paused": "⏸ Paused",
    "stopped": "■ Stopped",
    "closed": "MusicBee closed",
}


def fmt_ms(ms):
    total = max(0, int(ms)) // 1000
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _card(state, status_line, title="—", artist="—", album="—",
          position_ms=0, duration_ms=0, progress_label="", updated_at=None):
    percent = round(position_ms * 100 / duration_ms) if duration_ms else 0
    return {
        "state": state,
        "state_label": STATE_LABELS.get(state, status_line),
        "status_line": status_line,
        "title": title,
        "artist": artist,
        "album": album,
        "position_ms": position_ms,
        "duration_ms": duration_ms,
        "progress_label": progress_label,
        "progress_percent": percent,
        "updated_at": updated_at,
    }


def build_now_playing(path, now):
    """`now` is a timezone-aware datetime."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return _card("no-data", "No data — is the MusicBee plugin installed?")
    except (OSError, ValueError):
        # Caught mid-write (or briefly locked); the next refresh will read it.
        return _card("unavailable", "Waiting for MusicBee…")

    state = str(data.get("state") or "stopped").lower()
    updated_at = data.get("updated_at")
    try:
        age_s = (now - datetime.fromisoformat(updated_at)).total_seconds()
    except (TypeError, ValueError):
        age_s = STALE_AFTER_S + 1
    if age_s > STALE_AFTER_S:
        state = "closed"

    duration = max(0, int(data.get("duration_ms") or 0))
    position = max(0, int(data.get("position_ms") or 0))
    if state == "playing":
        position += int(max(0.0, age_s) * 1000)
    if duration:
        position = min(position, duration)
        progress = f"{fmt_ms(position)} / {fmt_ms(duration)}"
    else:
        progress = fmt_ms(position)

    label = STATE_LABELS.get(state, state.title())
    status_line = f"{label} · {progress}" if state in ("playing", "paused") else label
    return _card(
        state, status_line,
        title=data.get("title") or "Unknown title",
        artist=data.get("artist") or "—",
        album=data.get("album") or "—",
        position_ms=position, duration_ms=duration,
        progress_label=progress, updated_at=updated_at,
    )
