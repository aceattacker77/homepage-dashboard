# CYBER://HUB — Homepage dashboard

My personal [Homepage](https://gethomepage.dev) dashboard: Hermes agent
status, what I've been learning, headlines, containers and the track playing
in MusicBee, styled as "soft glass".

It is two pieces:
- **Homepage itself**, running in Docker.
- **A small host-side status API** (FastAPI, port 8787). It feeds every custom
  card, because Homepage can't run custom widget code.

```
Hermes state files ─┐
Obsidian vault (git)├─▶ status-api (FastAPI, host :8787) ◀─ MusicBee plugin JSON
nvidia-smi, RSS, YT ┘            ▲
                                 │  http://host.docker.internal:8787
                     Homepage (Docker :3000) ── docker.sock (read-only)
```

## What's on the page

| Row | Card | Source |
|---|---|---|
| **Hermes Agents** | Agent Status | `/hermes-status` shows worker and builder liveness and last activity |
| | OpenRouter Credits | `/openrouter-credits` shows balance, amount used and usage % |
| | Cron Jobs | `/cron-status` shows the next and last run of each Hermes job |
| | GPU | `/gpu-status` shows `nvidia-smi` readings: load, VRAM, temperature and power |
| **Mind** | Skills Learned | `/skills-learned` shows new (non-bundled) Hermes skills per week, an 8-week sparkline and the latest skill |
| | Second Brain | `/second-brain` shows the note of the day from the Obsidian vault (it opens in Obsidian) and the notes added this week |
| | Headlines | `/rss-digest` shows the latest items from `rss_feeds.json`; each headline links to its article |
| | Files | `/everything` queries [Everything](https://www.voidtools.com) for two lists. **Recent** shows the newest documents, images, media and archives in Desktop, Documents, Downloads, Pictures, Videos and OneDrive. **Downloads > 30 days** shows the space you could reclaim, then the 3 biggest old files. Rows open in Everything's web UI; the search box opens a search there. |
| **Infrastructure** | Homepage, FreshRSS | Docker container state plus CPU, RAM and network |
| | JDownloader 2 | Homepage's native `jdownloader` widget (login from `.env`) |
| | Now Playing | `/now-playing` shows MusicBee's current track (see [musicbee-plugin/](musicbee-plugin/README.md)) |
| **YouTube** (collapsed) | 6 channel cards | `/youtube-feeds?channel=…` shows the latest uploads; each one links to its video |

At the top are the resources widget (CPU, RAM, disk, uptime) and a DuckDuckGo
search box. At the bottom is a row of bookmarks.

## Setup

**Requirements:**
- Windows 11 with Docker Desktop.
- Python 3.11+.
- Hermes Agent running natively, for the Hermes cards.
- Optional: an Obsidian vault kept in git, MusicBee, and an NVIDIA GPU.

1. **Secrets.** Copy `.env.example` to `.env`, then fill in `JD_USERNAME` and
   `JD_PASSWORD`. For the Files card, also fill in `EVERYTHING_USER` and
   `EVERYTHING_PASS`: Everything 1.5's HTTP server login (Tools → Options →
   HTTP Server, port 8089). `.env` is gitignored.

2. **Status API.**
   ```powershell
   cd status-api
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   .venv\Scripts\python.exe status_api.py      # http://localhost:8787/health
   ```
   To start it at logon without a console window, put a copy of
   `launch-hidden.vbs` in `shell:startup`. Edit the `appDir` path in that
   file first if the repo lives somewhere else.

3. **Homepage.**
   ```powershell
   docker compose up -d                       # http://localhost:3000
   ```

4. **Optional: the MusicBee card.** Run `musicbee-plugin\build.ps1 -Install`,
   then restart MusicBee.

The paths in `status-api/status_api.py` default to this machine's layout:
`HERMES_BASE`, `SECOND_BRAIN_DIR` and `MUSICBEE_NOW_PLAYING`. Override them
with environment variables. The [status API README](status-api/README.md)
documents each endpoint, its caching and its variables.

## Repository layout

| Path | What it is |
|---|---|
| `docker-compose.yml` | The Homepage container: mounts `config/` and the Docker socket (read-only), and maps `host.docker.internal` |
| `config/services.yaml` | Every card and group |
| `config/settings.yaml` | Theme, row layout, equal-height cards, status dots |
| `config/widgets.yaml` | The top bar: resources and search |
| `config/custom.css` | The soft glass theme |
| `config/bookmarks.yaml`, `docker.yaml` | Bookmarks; the Docker socket used for container stats |
| `status-api/` | The JSON API behind the custom cards, with its tests |
| `musicbee-plugin/` | The C# MusicBee plugin for Now Playing. A standalone copy lives at [aceattacker77/musicbee-homepage-now-playing](https://github.com/aceattacker77/musicbee-homepage-now-playing). |
| `docs/superpowers/plans/` | The design and implementation plan for the Mind cards and the restyle |

## Customising

- **Layout.** Every service group is a full-width row. Set it in
  `settings.yaml` under `layout:` (`style: row`, `columns: N`). The order of
  keys there is the order on the page. Homepage has no `grid` style, so any
  other value silently falls back to narrow columns.
- **Theme.** The colours, glass opacity and corner radii are CSS variables
  at the top of `config/custom.css`. The rules target Homepage's semantic
  classes (`.service-card`, `.service-block`, `.service-group-name`), not
  Tailwind utility classes.
- **Adding a custom card:**
  1. Add a function and route to `status-api/status_api.py`. Put the logic in
     its own module with tests; `skills_learned.py` is an example.
  2. Point a `customapi` widget at `{{HOMEPAGE_VAR_STATUS_API}}/your-route`.
- **Widget URLs.** Always use `{{HOMEPAGE_VAR_STATUS_API}}`, never
  `localhost`. Homepage fetches widget data from inside its container.

## Tests

```powershell
cd status-api
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
musicbee-plugin\tests\run-smoke-test.ps1    # from the repo root
```

## Security notes

- **Secrets:** no secrets live in this repo. The JDownloader login comes from
  `.env`, and the OpenRouter key is read at runtime from Hermes' own `.env`.
- **What the status API reads and writes:**
  - It is read-only toward Hermes and the vault.
  - Its only writes are `status-api/state/`: the skills ledger and the note of
    the day. That folder is gitignored.
- **Network exposure:**
  - The status API binds `0.0.0.0:8787` with no authentication, so the
    Homepage container can reach it.
  - That exposes vault note excerpts, the current track and agent status to
    your LAN.
  - Keep the port firewalled to the local machine.
- **Docker socket:** it is mounted read-only. Homepage uses it only for
  container stats.
