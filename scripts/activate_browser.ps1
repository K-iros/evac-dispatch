$ws = New-Object -ComObject WScript.Shell
$ok = $ws.AppActivate('灾前疏散调度大脑')
if (-not $ok) { $ok = $ws.AppActivate('localhost:5300') }
if (-not $ok) { $ok = $ws.AppActivate('Chrome') }
if (-not $ok) { $ok = $ws.AppActivate('Edge') }
Write-Output "activated=$ok"
