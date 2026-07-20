Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "C:\Users\Administrator\.kimi-code\bin\kimi.exe" "web" "--port" "5494" "--host" "--dangerous-bypass-auth" "--allow-remote-terminals" "--allowed-host" "ai.r3ppx952a.nyat.app" "--no-open", 0, False
Set WshShell = Nothing
