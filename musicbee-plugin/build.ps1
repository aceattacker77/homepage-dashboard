# Builds mb_HomepageNowPlaying.dll with the C# compiler that ships with
# .NET Framework 4.x (no SDK or NuGet needed). -Install copies it into the
# per-user MusicBee plugin folder; restart MusicBee to load it.
param([switch]$Install)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$fx = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319'
$out = Join-Path $here 'bin\mb_HomepageNowPlaying.dll'

New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
& (Join-Path $fx 'csc.exe') -nologo -optimize+ -target:library "-out:$out" `
    "-r:$(Join-Path $fx 'System.Web.Extensions.dll')" `
    (Join-Path $here 'MusicBeeInterface.cs') (Join-Path $here 'HomepageNowPlaying.cs')
if ($LASTEXITCODE -ne 0) { throw "csc failed ($LASTEXITCODE)" }
Write-Output "Built $out"

if ($Install) {
    $plugins = Join-Path $env:APPDATA 'MusicBee\Plugins'
    Copy-Item $out $plugins -Force
    Write-Output "Installed to $plugins -- restart MusicBee to load it."
}
