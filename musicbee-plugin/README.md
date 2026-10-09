# Homepage Now Playing (MusicBee plugin)

Shows MusicBee's current track on the Homepage dashboard ("Now Playing" card
in the Infrastructure row).

```
MusicBee ──plugin──▶ %APPDATA%\MusicBee\HomepageNowPlaying\nowplaying.json
                           │  (on track / play-state change + every 5 s)
status API /now-playing ◀──┘  (../status-api/now_playing.py)
        │
Homepage customapi card ◀─┘  (refresh 5 s)
```

The plugin only writes a local file; it opens no network port. While a track
is playing the status API extrapolates the position from the file's
timestamp, so the progress keeps moving between writes. If the heartbeat is
more than 20 s old the card shows "MusicBee closed".

## Build and install

A prebuilt DLL, with its SHA-256 checksum, is in the
[v1.0.0 release](https://github.com/aceattacker77/musicbee-homepage-now-playing/releases/tag/v1.0.0)
of the standalone repo. Put it in `%APPDATA%\MusicBee\Plugins` and skip the
build step. Or build it from this folder:

```powershell
.\build.ps1 -Install   # builds bin\mb_HomepageNowPlaying.dll, copies it to %APPDATA%\MusicBee\Plugins
```

Then restart MusicBee. It appears under Edit → Preferences → Plugins as
"Homepage Now Playing". No admin rights needed: MusicBee also loads plugins
from the per-user `%APPDATA%\MusicBee\Plugins` folder.

Uses the C# compiler that ships with Windows' .NET Framework 4.x, so no SDK or
NuGet download is needed. That compiler is C# 5, so the plugin avoids newer
syntax (no `$""`, `?.`, `=>` members).

## Test (no MusicBee needed)

```powershell
.\tests\run-smoke-test.ps1
```

Drives the plugin through a fake MusicBee API: startup, pause, empty-title
fallback, heartbeat, shutdown. Exit code 0 = all passed. The status API side
is covered by `../status-api/tests/test_now_playing.py`.

## Uninstall

Disable/remove it in MusicBee's Preferences → Plugins (this also deletes the
`HomepageNowPlaying` folder), or delete
`%APPDATA%\MusicBee\Plugins\mb_HomepageNowPlaying.dll` while MusicBee is closed.

## `MusicBeeInterface.cs`

The official MusicBee plugin API definition (API revision 53), vendored
unmodified. getmusicbee.com/help/api is behind a bot check, so this copy
comes from the DiscordBee plugin's repository
(github.com/sll552/DiscordBee, Apache-2.0, blob e677a2be).
