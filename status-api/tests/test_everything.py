import everything as ev

NOW_MS = 1790000000000  # 2026-09-21 fixed clock
# FILETIME for NOW_MS - 12 minutes; > 2**53 so it must survive as a string.
FT_12M = str((NOW_MS - 12 * 60000 + ev.FILETIME_EPOCH_MS) * 10000)


def fake_fetch(calls):
    def fetch(query, count, sort=False):
        calls.append((query, count, sort))
        if count == ev.RECENT_COUNT:
            return {"totalResults": 999, "results": [
                {"type": "file", "name": "notes.md", "path": "C:\\Users\\Admin\\second-brain",
                 "size": "2048", "date_modified": FT_12M}]}
        return {"totalResults": len(calls) * 10}
    return fetch


def test_filetime_conversion_uses_integer_maths():
    assert int(FT_12M) > 2 ** 53
    assert ev.filetime_to_ms(FT_12M) == NOW_MS - 12 * 60000
    assert ev.filetime_to_ms("garbage") is None


def test_human_size():
    assert ev.human_size("512") == "512 B"
    assert ev.human_size("2048") == "2.0 KB"
    assert ev.human_size(str(3 * 1024 ** 3)) == "3.0 GB"
    assert ev.human_size(None) == "—"


def test_build_card_counts_and_recent():
    calls = []
    out = ev.build_everything(fake_fetch(calls), ev.DEFAULT_EXCLUDES, "2gb", NOW_MS)
    assert out["status"] == "ok"
    assert all(isinstance(out[k], int) for k in ("indexed", "changed_today", "huge", "downloads"))
    item = out["items"][0]
    assert item["name"] == "notes.md" and item["folder"] == "second-brain"
    assert item["ago"] == "12m ago" and item["size"] == "2.0 KB"
    queries = {q: (c, s) for q, c, s in calls}
    assert queries[""] == (1, False)
    assert "file: size:>2gb" in queries
    recent = [q for q, (c, s) in queries.items() if s][0]
    assert '!"C:\\Windows\\"' in recent and '!"$Recycle.Bin"' in recent
    assert all(c in (1, ev.RECENT_COUNT) for _, c, _ in calls)   # always pass c=


def test_offline_is_a_label_not_a_stack():
    def down(*_a, **_k):
        raise ev.EverythingOffline("refused")
    out = ev.build_everything(down, [], "2gb", NOW_MS)
    assert out["status"] == "offline" and out["indexed_label"] == "offline"
    assert out["items"] == []


def test_auth_failure():
    def denied(*_a, **_k):
        raise ev.EverythingAuthError()
    assert ev.build_everything(denied, [], "2gb", NOW_MS)["status"] == "auth"


def test_parse_excludes():
    assert ev.parse_excludes(None) == ev.DEFAULT_EXCLUDES
    assert ev.parse_excludes(r'C:\Temp\; "$Recycle.Bin"') == [r'"C:\Temp\"', '"$Recycle.Bin"']


def test_validate_url_blocks_other_hosts():
    assert ev.validate_url("http://host.docker.internal:8089/") == "http://host.docker.internal:8089"
    for bad in ("http://example.com:8089", "file:///c:/", ""):
        try:
            ev.validate_url(bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def test_long_names_are_truncated():
    def fetch(query, count, sort=False):
        return {"totalResults": 1, "results": [
            {"name": "4b3af7bf-165c-4cdb-af9c-8731499b4554.jsonl",
             "path": r"C:\Users\Admin\.claude\projects\C--Users-Admin-AppData-Local-hermes",
             "size": "1", "date_modified": FT_12M}]}
    item = ev.build_everything(fetch, [], "2gb", NOW_MS)["items"][0]
    assert len(item["name"]) == ev.NAME_MAX and item["name"].endswith("…")
    assert len(item["folder"]) == ev.FOLDER_MAX and item["folder"].endswith("…")
    assert item["label"].startswith(item["folder"] + " · ")
    assert ev.truncate("short.txt", ev.NAME_MAX) == "short.txt"
