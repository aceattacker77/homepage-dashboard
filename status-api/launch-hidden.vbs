' Launch the Hermes status API with no visible console window.
' Used as the scheduled-task target so logon does not flash a cmd window.
Dim shell, appDir
appDir = "C:\Users\Admin\docker\homepage\status-api"
Set shell = CreateObject("WScript.Shell")
shell.Run """" & appDir & "\run-status-api.bat""", 0, False