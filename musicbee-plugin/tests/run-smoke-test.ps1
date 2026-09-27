# Compiles the plugin together with PluginSmokeTest.cs into a console exe and
# runs it against a fake MusicBee API. No MusicBee needed. Exit code 0 = pass.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$fx = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319'
$exe = Join-Path $root 'bin\PluginSmokeTest.exe'

New-Item -ItemType Directory -Force (Split-Path $exe) | Out-Null
& (Join-Path $fx 'csc.exe') -nologo -target:exe "-out:$exe" `
    "-r:$(Join-Path $fx 'System.Web.Extensions.dll')" `
    (Join-Path $root 'MusicBeeInterface.cs') (Join-Path $root 'HomepageNowPlaying.cs') `
    (Join-Path $root 'tests\PluginSmokeTest.cs')
if ($LASTEXITCODE -ne 0) { throw "csc failed ($LASTEXITCODE)" }
& $exe @args
exit $LASTEXITCODE
