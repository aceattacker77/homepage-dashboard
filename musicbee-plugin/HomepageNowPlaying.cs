// Homepage Now Playing -- MusicBee plugin.
//
// Writes the current track to <MusicBee storage>\HomepageNowPlaying\nowplaying.json
// on every track / play-state change and every HeartbeatMs as a heartbeat.
// The Hermes status API (../status-api/now_playing.py) serves that file to the
// Homepage dashboard at /now-playing. The plugin never opens a network port.
//
// Written for the C# 5 compiler that ships with .NET Framework 4.x
// (see build.ps1), so no newer language features.

using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace MusicBeePlugin
{
    public partial class Plugin
    {
        private const int HeartbeatMs = 5000;
        private const string OutputFolder = "HomepageNowPlaying";
        private const string OutputFile = "nowplaying.json";

        private MusicBeeApiInterface mbApiInterface;
        private readonly PluginInfo about = new PluginInfo();
        private readonly object writeLock = new object();
        private Timer heartbeat;
        private string outputPath;
        private bool closed;

        public PluginInfo Initialise(IntPtr apiInterfacePtr)
        {
            mbApiInterface = new MusicBeeApiInterface();
            mbApiInterface.Initialise(apiInterfacePtr);

            about.PluginInfoVersion = PluginInfoVersion;
            about.Name = "Homepage Now Playing";
            about.Description = "Shares the current track with the Homepage dashboard (writes a local JSON file)";
            about.Author = "Ace Attacker";
            about.TargetApplication = "";
            about.Type = PluginType.General;
            about.VersionMajor = 1;
            about.VersionMinor = 0;
            about.Revision = 0;
            about.MinInterfaceVersion = MinInterfaceVersion;
            about.MinApiRevision = MinApiRevision;
            about.ReceiveNotifications = ReceiveNotificationFlags.PlayerEvents;
            about.ConfigurationPanelHeight = 0;
            return about;
        }

        public bool Configure(IntPtr panelHandle)
        {
            return false;
        }

        public void SaveSettings()
        {
        }

        public void Close(PluginCloseReason reason)
        {
            Shutdown();
        }

        public void Uninstall()
        {
            Shutdown();
            try
            {
                string folder = Path.GetDirectoryName(OutputPath());
                if (Directory.Exists(folder))
                    Directory.Delete(folder, true);
            }
            catch (Exception)
            {
                // Leaving a stale folder behind is harmless.
            }
        }

        public void ReceiveNotification(string sourceFileUrl, NotificationType type)
        {
            switch (type)
            {
                case NotificationType.PluginStartup:
                    closed = false;
                    WriteState(null);
                    heartbeat = new Timer(delegate { WriteState(null); }, null, HeartbeatMs, HeartbeatMs);
                    break;
                case NotificationType.TrackChanged:
                case NotificationType.PlayStateChanged:
                    WriteState(null);
                    break;
                case NotificationType.ShutdownStarted:
                    Shutdown();
                    break;
            }
        }

        // Stop the heartbeat and leave a "closed" record so the dashboard
        // does not wait for the heartbeat to go stale.
        private void Shutdown()
        {
            Timer t = heartbeat;
            heartbeat = null;
            if (t != null)
                t.Dispose();
            WriteState("closed");
        }

        private string OutputPath()
        {
            if (outputPath == null)
            {
                string root = mbApiInterface.Setting_GetPersistentStoragePath();
                outputPath = Path.Combine(Path.Combine(root, OutputFolder), OutputFile);
            }
            return outputPath;
        }

        private static string StateName(PlayState state)
        {
            switch (state)
            {
                case PlayState.Playing: return "playing";
                case PlayState.Paused: return "paused";
                case PlayState.Loading: return "playing";
                default: return "stopped";
            }
        }

        // Runs on MusicBee's notification thread and on the timer thread;
        // writeLock keeps the two from interleaving. Must never throw into
        // MusicBee.
        private void WriteState(string forcedState)
        {
            lock (writeLock)
            {
                if (closed)
                    return;
                try
                {
                    string url = mbApiInterface.NowPlaying_GetFileUrl();
                    string title = mbApiInterface.NowPlaying_GetFileTag(MetaDataType.TrackTitle);
                    if (string.IsNullOrEmpty(title) && !string.IsNullOrEmpty(url))
                        title = Path.GetFileNameWithoutExtension(url);

                    var data = new Dictionary<string, object>();
                    data["state"] = forcedState ?? StateName(mbApiInterface.Player_GetPlayState());
                    data["title"] = title ?? "";
                    data["artist"] = mbApiInterface.NowPlaying_GetFileTag(MetaDataType.Artist) ?? "";
                    data["album"] = mbApiInterface.NowPlaying_GetFileTag(MetaDataType.Album) ?? "";
                    data["album_artist"] = mbApiInterface.NowPlaying_GetFileTag(MetaDataType.AlbumArtist) ?? "";
                    data["position_ms"] = mbApiInterface.Player_GetPosition();
                    data["duration_ms"] = mbApiInterface.NowPlaying_GetDuration();
                    data["updated_at"] = DateTime.UtcNow.ToString("o");
                    data["plugin_version"] = "1.0.0";

                    string json = new JavaScriptSerializer().Serialize(data);
                    string path = OutputPath();
                    Directory.CreateDirectory(Path.GetDirectoryName(path));

                    // Write-then-swap so the status API never reads half a file.
                    string tmp = path + ".tmp";
                    File.WriteAllText(tmp, json, new UTF8Encoding(false));
                    if (File.Exists(path))
                        File.Replace(tmp, path, null);
                    else
                        File.Move(tmp, path);
                }
                catch (Exception)
                {
                    // A missed update is corrected by the next heartbeat.
                }
                // Set under the lock so a heartbeat already waiting on it
                // cannot overwrite the "closed" record.
                if (forcedState == "closed")
                    closed = true;
            }
        }
    }
}
