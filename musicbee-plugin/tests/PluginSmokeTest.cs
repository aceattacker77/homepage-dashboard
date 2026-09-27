// Drives the plugin through a fake MusicBee API (no MusicBee needed) and
// checks the JSON it writes. Build + run: tests\run-smoke-test.ps1
using System;
using System.IO;
using System.Reflection;
using System.Threading;
using MusicBeePlugin;

static class PluginSmokeTest
{
    static int failures;

    static void Check(bool ok, string what)
    {
        Console.WriteLine((ok ? "PASS  " : "FAIL  ") + what);
        if (!ok) failures++;
    }

    static int Main(string[] args)
    {
        string storage = Path.Combine(Path.GetTempPath(), "mbnp-test-" + Guid.NewGuid().ToString("N"));
        string file = Path.Combine(storage, @"HomepageNowPlaying\nowplaying.json");
        Plugin.PlayState state = Plugin.PlayState.Playing;
        string title = "Idioteque";

        var api = new Plugin.MusicBeeApiInterface();
        api.Setting_GetPersistentStoragePath = () => storage;
        api.NowPlaying_GetFileUrl = () => @"D:\Music\Radiohead\Kid A\08 Idioteque.flac";
        api.NowPlaying_GetFileTag = field =>
            field == Plugin.MetaDataType.TrackTitle ? title :
            field == Plugin.MetaDataType.Artist ? "Radiohead \"quoted\"" :
            field == Plugin.MetaDataType.Album ? "Kid A" : null;
        api.Player_GetPlayState = () => state;
        api.Player_GetPosition = () => 61000;
        api.NowPlaying_GetDuration = () => 309000;

        var plugin = new Plugin();
        typeof(Plugin).GetField("mbApiInterface", BindingFlags.NonPublic | BindingFlags.Instance)
            .SetValue(plugin, api);

        plugin.ReceiveNotification(null, Plugin.NotificationType.PluginStartup);
        string json = File.ReadAllText(file);
        Check(json.Contains("\"state\":\"playing\""), "startup writes playing state");
        Check(json.Contains("\"title\":\"Idioteque\""), "title written");
        Check(json.Contains("\"artist\":\"Radiohead \\\"quoted\\\"\""), "quotes escaped in JSON");
        Check(json.Contains("\"position_ms\":61000") && json.Contains("\"duration_ms\":309000"), "position and duration");
        Check(!File.Exists(file + ".tmp"), "no temp file left behind");

        title = "";
        state = Plugin.PlayState.Paused;
        plugin.ReceiveNotification(null, Plugin.NotificationType.PlayStateChanged);
        json = File.ReadAllText(file);
        Check(json.Contains("\"state\":\"paused\""), "pause written");
        Check(json.Contains("\"title\":\"08 Idioteque\""), "empty title falls back to file name");

        state = Plugin.PlayState.Playing;
        DateTime before = File.GetLastWriteTimeUtc(file);
        Thread.Sleep(5600);
        Check(File.GetLastWriteTimeUtc(file) > before, "heartbeat rewrites the file");

        plugin.ReceiveNotification(null, Plugin.NotificationType.ShutdownStarted);
        Check(File.ReadAllText(file).Contains("\"state\":\"closed\""), "shutdown writes closed");
        Thread.Sleep(5600);
        Check(File.ReadAllText(file).Contains("\"state\":\"closed\""), "no heartbeat after shutdown");
        plugin.Close(Plugin.PluginCloseReason.MusicBeeClosing);   // must not throw

        // Hand the file to the status API side for the end-to-end check.
        if (args.Length > 0) File.Copy(file, args[0], true);
        Directory.Delete(storage, true);
        Console.WriteLine(failures == 0 ? "ALL PASSED" : failures + " FAILED");
        return failures == 0 ? 0 : 1;
    }
}
