Option Explicit

Dim shell, files, projectDir, serverScript
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
projectDir = files.GetParentFolderName(WScript.ScriptFullName)
serverScript = files.BuildPath(projectDir, "start_server.bat")

If Not files.FileExists(serverScript) Then
    WScript.Echo "Missing start_server.bat next to start_server_hidden.vbs."
    WScript.Quit 1
End If

shell.Run """" & serverScript & """", 0, False
