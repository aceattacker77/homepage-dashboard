# Hermes Status API

Read-only JSON status surface that backs the five **Custom API** widgets on the
Homepage dashboard (`http://localhost:3000`).

It never creates, edits, pauses or fires a cron job, and never sends messages.
It only **reads** Hermes state files and shells out to read-only commands
(`nvidia-smi`).

## Endpoints

| Endpoint | Backs widget | Source |
|---|---|---|
| `/health` | — (liveness probe) | — |
| `/hermes-status` | Agent Status | `gateway_state.json` + PID check, `state.db` sessions, `config.yaml` |
| `/openrouter-credits` | OpenRouter Credits | `https://openrouter.ai/api/v1/credits` |
| `/cron-status` | Cron Jobs | `<hermes>/cron/jobs.json` + `executions.db` |
| `/rss-digest` | Headlines | `<hermes>/rss_feeds.json` (same feed list as the 18:00 digest) |
| `/youtube-feeds?channel=<key>` | YouTube (one card per channel) | `youtube_channels.json` + YouTube's public feed |
| `/youtube-channels` | — (index of configured channels) | `youtube_channels.json` |
| `/gpu-status` | GPU | `nvidia-smi` on the host |
| `/skills-learned` | Skills Learned | `skills/` + `profiles/*/skills/` vs bundled `hermes-agent/{skills,optional-skills}`; `state/skills_ledger.json` |
| `/second-brain` | Second Brain | `C:\Users\Admin\second-brain` (files + `git log`, read-only) |

Port **8787**. Binds `0.0.0.0` so the Homepage container can reach it.

## Why `host.docker.internal`, not `localhost`

Homepage fetches Custom API widget URLs **server-side, from inside its own
container**. `http://localhost:8787` there would resolve to the Homepage
container itself. The widget URLs therefore use
`{{HOMEPAGE_VAR_STATUS_API}}` = `http://host.docker.internal:8787`, defined in
`../docker-compose.yml`.

## YouTube channels

Homepage has **no native RSS/YouTube widget**. Verified against
`src/widgets/` and `src/components/widgets/` at v2.3.0 *and* `dev`: the only
rss-ish entry is the unrelated `freshrss` service widget. (An earlier grep hit
on `rssProxyHandler` was a false positive — that string is inside
`freshrssProxyHandler`.) So per-channel uploads go through the Custom API
widget instead.

`youtube_channels.json` holds the channel list. Each `channel_id` was resolved
from the live YouTube channel page (`externalId` + `vanityChannelUrl`) and then
confirmed against the channel name YouTube's own feed reports. The API returns
`channel` (what YouTube says), `expected_name` (what the config claims) and
`name_matches`, so an ID mix-up is visible rather than silent.

Gotchas worth remembering:

- `@AsmongoldTV` **does not exist** (404). The real handle is `@AsmonTV`.
- On the ESPN FC page the first `"channelId"` string is
  `UCiWLfSweyRNmLpgEHekhoAg` — the **ESPN** channel, not ESPN FC. `externalId`
  (`UC6c1z7bA__85CIWZ_jpCK-Q`) is the correct one. Always cross-check against
  the feed's channel `<title>`, not the first ID you find in the page source.
- A separate auto-generated `MIRAGE OVERDRIVE JP - Topic` channel exists; it is
  deliberately not used in favour of the artist's own channel.

Dashboard-only: this is independent of `rss_feeds.json` and the digest pipeline.

## Running it

```bash
# foreground
.venv/Scripts/python.exe status_api.py

# background / hidden (what the autostart entry uses)
wscript.exe launch-hidden.vbs
```

Autostart: `launch-hidden.vbs` is copied into the user's Startup folder as
`HermesStatusAPI.vbs`, so it starts at logon with no console window — the same
mechanism Hermes' own gateway uses on this box. (`schtasks` needs elevation,
so the Startup folder is the user-level route.)

Own virtualenv (`.venv/`) holds FastAPI + uvicorn, so the service does not
depend on the Hermes venv.

## Notable implementation details

- **Never call `os.kill(pid, 0)` on Windows** — Python maps it to
  `TerminateProcess` and it *kills* the process. Liveness uses
  `OpenProcess`/`GetExitCodeProcess` via `ctypes` instead.
- **Last activity comes from `state.db` → `sessions.last_activity_at`**, not
  from the cron ticker heartbeat. The heartbeat is touched constantly and would
  peg every agent at "1s ago".
- `state.db` and `executions.db` are opened SQLite read-only
  (`file:...?mode=ro`).
- Per-endpoint TTL caches (RSS 10 min, cron 30 s, credits 60 s, GPU 5 s) so
  widget refreshes stay cheap and the RSS digest does not hammer 11 feeds.
- GPU: Homepage's built-in `resources` widget has **no** GPU option (only the
  Glances widget does), so the host GPU is surfaced here via `nvidia-smi`
  rather than by adding a Glances container.

## Skills ledger

`state/skills_ledger.json` freezes the date each skill name was first seen.
The first sighting is seeded from the earliest creation/modification time
of any file in any copy of that skill. After that, edits, copies and backup
restores cannot move it. Delete the file to re-seed from timestamps. It is
gitignored and is this API's only write.

## Tests

```bash
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
```

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `HERMES_STATUS_PORT` | `8787` | Listen port |
| `HERMES_BASE` | `C:\Users\Admin\AppData\Local\hermes` | Hermes base dir (default profile = worker agent) |
| `SECOND_BRAIN_DIR` | `C:\Users\Admin\second-brain` | Obsidian vault folder |
| `SECOND_BRAIN_VAULT` | `second-brain` | Vault name used in `obsidian://` links |

`OPENROUTER_API_KEY` is read from `$HERMES_HOME/.env`
(`profiles/hermes-builder/.env`), falling back to the base `.env`, then the
process environment. Query `hermes-agent` src: never logged or echoed.