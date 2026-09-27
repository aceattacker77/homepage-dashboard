import json
from datetime import datetime, timedelta, timezone

import now_playing as np_

NOW = datetime(2026, 9, 27, 13, 0, 0, tzinfo=timezone.utc)


def write_state(tmp_path, ago_s=1, bom=False, **fields):
    data = {"state": "playing", "title": "Idioteque", "artist": "Radiohead",
            "album": "Kid A", "position_ms": 60000, "duration_ms": 245000,
            "updated_at": (NOW - timedelta(seconds=ago_s)).isoformat()}
    data.update(fields)
    path = tmp_path / "nowplaying.json"
    text = json.dumps(data)
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return path


def test_missing_file_explains_setup(tmp_path):
    out = np_.build_now_playing(tmp_path / "nowplaying.json", NOW)
    assert out["state"] == "no-data"
    assert out["title"] == "—"
    assert "plugin" in out["status_line"].lower()


def test_playing_extrapolates_position(tmp_path):
    out = np_.build_now_playing(write_state(tmp_path, ago_s=3), NOW)
    assert out["state"] == "playing"
    assert out["position_ms"] == 63000
    assert out["progress_label"] == "1:03 / 4:05"
    assert out["status_line"] == "▶ Playing · 1:03 / 4:05"
    assert out["progress_percent"] == 26


def test_position_clamped_to_duration(tmp_path):
    out = np_.build_now_playing(write_state(tmp_path, ago_s=15, position_ms=240000), NOW)
    assert out["position_ms"] == 245000


def test_paused_does_not_extrapolate(tmp_path):
    out = np_.build_now_playing(write_state(tmp_path, ago_s=10, state="paused"), NOW)
    assert out["position_ms"] == 60000
    assert out["status_line"] == "⏸ Paused · 1:00 / 4:05"


def test_stale_heartbeat_means_closed(tmp_path):
    out = np_.build_now_playing(write_state(tmp_path, ago_s=np_.STALE_AFTER_S + 1), NOW)
    assert out["state"] == "closed"
    assert out["status_line"] == "MusicBee closed"
    assert out["title"] == "Idioteque"          # last track still shown


def test_closed_state_from_plugin(tmp_path):
    out = np_.build_now_playing(write_state(tmp_path, state="closed"), NOW)
    assert out["state"] == "closed"


def test_stopped(tmp_path):
    out = np_.build_now_playing(write_state(tmp_path, state="stopped", position_ms=0), NOW)
    assert out["status_line"] == "■ Stopped"


def test_half_written_file_is_waiting_not_error(tmp_path):
    path = tmp_path / "nowplaying.json"
    path.write_text('{"state": "play', encoding="utf-8")
    out = np_.build_now_playing(path, NOW)
    assert out["state"] == "unavailable"
    assert out["status_line"] == "Waiting for MusicBee…"


def test_stream_without_duration(tmp_path):
    out = np_.build_now_playing(write_state(tmp_path, ago_s=0, duration_ms=0), NOW)
    assert out["progress_label"] == "1:00"
    assert out["progress_percent"] == 0


def test_long_track_uses_hours(tmp_path):
    out = np_.build_now_playing(write_state(tmp_path, ago_s=0, position_ms=3723000,
                                            duration_ms=7200000), NOW)
    assert out["progress_label"] == "1:02:03 / 2:00:00"


def test_dotnet_round_trip_timestamp(tmp_path):
    # C# DateTime.UtcNow.ToString("o") -> 7 fractional digits and a Z suffix.
    path = write_state(tmp_path, updated_at="2026-09-27T12:59:57.1234567Z")
    out = np_.build_now_playing(path, NOW)
    assert out["state"] == "playing"
    assert out["position_ms"] == 62876


def test_bom_and_missing_tags(tmp_path):
    out = np_.build_now_playing(write_state(tmp_path, bom=True, title="", artist=None,
                                            album=""), NOW)
    assert (out["title"], out["artist"], out["album"]) == ("Unknown title", "—", "—")
