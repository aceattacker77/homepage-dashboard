from datetime import datetime, timedelta

import everything as ev

NOW_MS = 1790000000000  # 2026-09-21 fixed clock
DAY_MS = 86400000
# FILETIME for NOW_MS - 12 minutes; > 2**53 so it must survive as a string.
FT_12M = str((NOW_MS - 12 * 60000 + ev.FILETIME_EPOCH_MS) * 10000)
FT_40D = str((NOW_MS - 40 * DAY_MS + ev.FILETIME_EPOCH_MS) * 10000)
GB = 1024 ** 3
WEB = "http://localhost:8089"


def row(name, path, size, ft):
    return {"type": "file", "name": name, "path": path, "size": str(size), "date_modified": ft}


def fake_fetch(calls, old=None):
    """Answers the three Files-card queries the way Everything would."""
    old = old if old is not None else [
        row("ubuntu.iso", r"C:\Users\Admin\Downloads", 5 * GB, FT_40D),
        row("game setup.exe", r"C:\Users\Admin\Downloads\installers", 2 * GB, FT_40D),
        row("notes.zip", r"C:\Users\Admin\Downloads", 1 * GB, FT_40D),
        row("tiny.txt", r"C:\Users\Admin\Downloads", 10, FT_40D),
    ]

    def fetch(query, count, sort=None):
        calls.append((query, count, sort))
        if sort == "date_modified":
            return {"totalResults": 1, "results": [
                row("Q3 report.pdf", r"C:\Users\Admin\Documents\work", 2048, FT_12M)]}
        return {"totalResults": len(old), "results": old[:count]}
    return fetch


def build(calls, **kw):
    return ev.build_files_card(fake_fetch(calls, **kw), WEB, 30, NOW_MS)


def test_filetime_conversion_uses_integer_maths():
    assert int(FT_12M) > 2 ** 53
    assert ev.filetime_to_ms(FT_12M) == NOW_MS - 12 * 60000
    assert ev.filetime_to_ms("garbage") is None


def test_human_size():
    assert ev.human_size("512") == "512 B"
    assert ev.human_size("2048") == "2.0 KB"
    assert ev.human_size(str(3 * GB)) == "3.0 GB"
    assert ev.human_size(None) == "—"


def test_recent_query_is_an_include_list():
    calls = []
    build(calls)
    query, count, sort = [c for c in calls if c[2] == "date_modified"][0]
    assert sort == "date_modified" and count == ev.RECENT_COUNT
    for folder in ev.MY_FOLDERS:
        assert f'"{folder}\\"' in query
    assert query.count("<") == 1 and "|" in query          # one OR-group of folders
    assert "ext:" in query and ";pdf;" in f";{query.split('ext:')[1].split()[0]};"
    # \Logs\: ShareX and several games log into Documents\<app>\Logs.
    for noise in (r'!"\.git\"', r'!"\.obsidian\"', '!"~$"', r'!"\Logs\"'):
        assert noise in query
    assert "AppData" not in query                          # no exclude-list whack-a-mole
    # Hermes writes the vault every few minutes; it would crowd out everything
    # else, and the Second Brain card already covers it.
    assert "second-brain" not in query


def test_cleanup_queries_use_the_cutoff_date():
    calls = []
    build(calls)
    cutoff = (datetime.fromtimestamp(NOW_MS / 1000) - timedelta(days=30)).date().isoformat()
    cleanup = [c for c in calls if c[2] != "date_modified"]
    assert {c[2] for c in cleanup} == {"size"}
    for query, _count, _sort in cleanup:
        assert query == f'file: "{ev.DOWNLOADS}\\" dm:<{cutoff}'
    assert sorted(c[1] for c in cleanup) == [ev.CLEANUP_TOP, ev.CLEANUP_SCAN]


def test_card_recent_rows():
    out = build([])
    assert out["status"] == "ok"
    item = out["recent"][0]
    assert item["name"] == "Q3 report.pdf"
    assert item["label"] == "work · 12m ago"
    assert item["href"] == WEB + "/?search=" + "%22C%3A%5CUsers%5CAdmin%5CDocuments%5Cwork%5CQ3%20report.pdf%22"


def test_card_cleanup_summary_and_biggest_files():
    out = build([])
    summary, *biggest = out["cleanup"]
    assert out["cleanup_files"] == 4 and out["cleanup_bytes"] == 8 * GB + 10
    assert summary["name"] == "Downloads > 30 days"
    assert summary["label"] == "8.0 GB · 4 files"
    assert summary["href"].startswith(WEB + "/?search=")
    assert [b["name"] for b in biggest] == ["ubuntu.iso", "game setup.exe", "notes.zip"]
    assert biggest[0]["label"] == "5.0 GB · 40d ago"


def test_cleanup_nothing_old():
    out = build([], old=[])
    assert out["cleanup"] == [{"name": "Downloads > 30 days", "label": "all tidy",
                               "href": out["cleanup"][0]["href"]}]
    assert out["cleanup_bytes"] == 0


def test_cleanup_total_marks_a_capped_scan():
    def fetch(query, count, sort=None):
        if sort == "date_modified":
            return {"totalResults": 0, "results": []}
        rows = [row(f"f{i}.bin", r"C:\Users\Admin\Downloads", GB, FT_40D) for i in range(count)]
        return {"totalResults": ev.CLEANUP_SCAN + 500, "results": rows}
    out = ev.build_files_card(fetch, WEB, 30, NOW_MS)
    assert out["cleanup"][0]["label"].startswith("≥ ")
    assert out["cleanup_files"] == ev.CLEANUP_SCAN + 500
    assert out["recent"] == [{"name": "No recent files", "label": "", "href": ""}]


def test_offline_is_a_row_not_a_stack():
    def down(*_a, **_k):
        raise ev.EverythingOffline("refused")
    out = ev.build_files_card(down, WEB, 30, NOW_MS)
    assert out["status"] == "offline"
    assert out["recent"] == [{"name": "Everything offline", "label": "", "href": ""}]
    assert out["cleanup"] == []


def test_auth_failure():
    def denied(*_a, **_k):
        raise ev.EverythingAuthError()
    out = ev.build_files_card(denied, WEB, 30, NOW_MS)
    assert out["status"] == "auth"
    assert out["recent"][0]["name"] == "Everything login failed"


def test_validate_url_blocks_other_hosts():
    assert ev.validate_url("http://host.docker.internal:8089/") == "http://host.docker.internal:8089"
    for bad in ("http://example.com:8089", "file:///c:/", ""):
        try:
            ev.validate_url(bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def test_long_names_are_truncated():
    def fetch(query, count, sort=None):
        if sort != "date_modified":
            return {"totalResults": 0, "results": []}
        return {"totalResults": 1, "results": [row(
            "4b3af7bf-165c-4cdb-af9c-8731499b4554 final final v2.docx",
            r"C:\Users\Admin\Documents\a very long project folder name", 1, FT_12M)]}
    item = ev.build_files_card(fetch, WEB, 30, NOW_MS)["recent"][0]
    assert len(item["name"]) == ev.NAME_MAX and item["name"].endswith("…")
    assert item["label"].split(" · ")[0].endswith("…")
    assert ev.truncate("short.txt", ev.NAME_MAX) == "short.txt"
