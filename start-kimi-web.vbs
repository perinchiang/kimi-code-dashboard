Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "C:\Users\Administrator\.kimi-code\bin\kimi.exe" "server" "run" "--port" "5494" "--host" "--dangerous-bypass-auth" "--allowed-host" "ai.r3ppx952a.nyat.app" "--foreground", 0, False
Set WshShell = Nothing
