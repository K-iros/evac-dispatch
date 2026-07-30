$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$base = 'http://localhost:5300/?noanim=1'
$out = 'd:\File\waitan\landing'
$shots = @(
    @{ name = 'hero';     url = $base;              size = '1600,1000' },
    @{ name = 'story';    url = "$base#story";      size = '1600,1900' },
    @{ name = 'how';      url = "$base#how";        size = '1600,1600' },
    @{ name = 'features'; url = "$base#features";   size = '1600,2400' },
    @{ name = 'tech';     url = "$base#tech";       size = '1600,2400' }
)
foreach ($s in $shots) {
    $file = Join-Path $out ("verify_" + $s.name + ".png")
    $args = @(
        '--headless=new', '--disable-gpu', '--hide-scrollbars',
        '--virtual-time-budget=6000',
        "--screenshot=$file",
        "--window-size=$($s.size)",
        $s.url
    )
    Start-Process -FilePath $edge -ArgumentList $args -Wait -WindowStyle Hidden
}
Get-ChildItem (Join-Path $out 'verify_*.png') | Select-Object Name, Length
