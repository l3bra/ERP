$ErrorActionPreference = 'Stop'

$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$startupScript = Join-Path $projectDirectory 'start_server_hidden.vbs'
if (-not (Test-Path -LiteralPath $startupScript)) {
    throw "Startup script not found: $startupScript"
}

$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
$action = New-ScheduledTaskAction -Execute $wscript `
    -Argument ('//B //NoLogo "' + $startupScript + '"')
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$principal = New-ScheduledTaskPrincipal -UserId $userId `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName 'ERP Warehouse API' `
    -Action $action -Trigger $trigger -Principal $principal `
    -Description 'Starts the local ERP warehouse API at user logon without opening a browser.' `
    -Force | Out-Null

Write-Host 'ERP Warehouse API will start at your next Windows sign-in.'
Write-Host 'Open http://127.0.0.1:8000/ in your browser to use the app.'
