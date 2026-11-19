# Installs (or replaces) the daily Hatlas feed update as a Windows task for the current user. No admin needed.
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_update_task.ps1
#   ... -Remove      takes the task away again
# The task runs tools/update_feeds.py every day at 09:00 without a console window (pyw), and later if the PC was
# off or offline at that time. Its log: %LOCALAPPDATA%\Hatlas\update.log
param([switch]$Remove, [string]$At = '09:00')

$name = 'Hatlas veri güncellemesi'
if ($Remove) {
  Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
  Write-Output "Removed: $name"
  return
}

$root = Split-Path -Parent $PSScriptRoot
$pyw = (Get-Command pyw -ErrorAction Stop).Source
$action = New-ScheduledTaskAction -Execute $pyw -Argument "-3 -I `"$root\tools\update_feeds.py`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
  -Description 'Hatlas: checks kk-gtfs and İBB for new transit data, rebuilds data/, commits it (never pushes) and warns before feeds end.' -Force | Out-Null
Write-Output "Installed: $name, every day at $At ($pyw)"
