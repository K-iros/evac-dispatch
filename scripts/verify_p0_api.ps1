$ErrorActionPreference = 'Stop'
$t0 = Get-Date
$r = Invoke-RestMethod 'http://127.0.0.1:8000/api/schedule?scenario=s2024' -TimeoutSec 180
Write-Host ("schedule s2024 in {0:n1}s" -f ((Get-Date) - $t0).TotalSeconds)
Write-Host ("accessCases: " + $r.accessCases.Count)
$r.accessCases | ForEach-Object {
  Write-Host ("  " + $_.evacueeId + " foot=" + $_.footKm + "km wheel=" + $_.wheelchairKm + "km x" + $_.detourRatio + " barrier=(" + $_.barrier.location.lng + "," + $_.barrier.location.lat + ")")
}
$fr = @($r.assignments | Where-Object { $_.footRoute })
Write-Host ("footRoute assignments: " + $fr.Count)
$fr | ForEach-Object { Write-Host ("  " + $_.evacueeId + " route=" + $_.route.Count + " foot=" + $_.footRoute.Count) }

$t1 = Get-Date
$b = Invoke-RestMethod 'http://127.0.0.1:8000/api/briefings?scenario=s2024' -TimeoutSec 120
Write-Host ("briefings in {0:n1}s source=" -f ((Get-Date) - $t1).TotalSeconds) -NoNewline
Write-Host $b.source
Write-Host ("items: " + $b.items.Count)
$b.items | Select-Object -First 4 | ForEach-Object { Write-Host ("  [" + $_.helperId + "] " + $_.helperName + ": " + $_.text) }
