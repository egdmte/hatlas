# Shows a Windows notification for tools/update_feeds.py (Windows PowerShell 5.1, no modules needed).
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\notify.ps1 -Title "Hatlas" -Message "..."
# The text is put into the notification as XML text (escaped), never run.
param(
  [Parameter(Mandatory = $true)][string]$Title,
  [Parameter(Mandatory = $true)][string]$Message
)

$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]

$t = [System.Security.SecurityElement]::Escape($Title)
$lines = ($Message -split "`n" | Select-Object -First 4 | ForEach-Object { "<text>$([System.Security.SecurityElement]::Escape($_))</text>" }) -join ''
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template=`"ToastGeneric`"><text>$t</text>$lines</binding></visual></toast>")

# Shown under Windows PowerShell's name: a script can't register its own app name without an installer.
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
