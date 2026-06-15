$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\HNOCS"
$OutputRoot = "D:\HNOCS\out\thermal-sa-tas-results\final\thermal-sa-tas-v3-integrated-seeds40-49"
$LogRoot = Join-Path $OutputRoot "_logs"
$Python = "D:\anaconda3\python.exe"

$env:OMNETPP_ROOT = "D:\omnetpp\omnetpp-6.3.0"
$env:PATH = "D:\HNOCS;D:\omnetpp\omnetpp-6.3.0\bin;D:\omnetpp\omnetpp-6.3.0\tools\win32.x86_64\clang64\bin;D:\omnetpp\omnetpp-6.3.0\tools\win32.x86_64\usr\bin;" + $env:PATH

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

$progressLog = Join-Path $LogRoot "progress.log"
"Thermal-SA-TAS v3 integrated seeds 40-49 started at $(Get-Date -Format o)" | Out-File -FilePath $progressLog -Encoding utf8
"Python: $Python" | Out-File -FilePath $progressLog -Append -Encoding utf8

Set-Location $ProjectRoot

foreach ($seed in 40..49) {
    $seedOut = Join-Path $OutputRoot ("seed_{0}" -f $seed)
    $seedLog = Join-Path $LogRoot ("seed_{0}.log" -f $seed)

    "START seed=$seed at $(Get-Date -Format o) out=$seedOut" | Out-File -FilePath $progressLog -Append -Encoding utf8

    & $Python "experiment\thermal_sa_tas_baseline\run_thermal_sa_tas.py" `
        --preset v3_integrated `
        --seed $seed `
        --out $seedOut `
        --omnet-timeout 300 `
        --verbose *>&1 | Tee-Object -FilePath $seedLog

    if ($LASTEXITCODE -ne 0) {
        "FAIL seed=$seed exit=$LASTEXITCODE at $(Get-Date -Format o)" | Out-File -FilePath $progressLog -Append -Encoding utf8
        exit $LASTEXITCODE
    }

    "DONE seed=$seed at $(Get-Date -Format o)" | Out-File -FilePath $progressLog -Append -Encoding utf8
}

"Thermal-SA-TAS v3 integrated seeds 40-49 finished at $(Get-Date -Format o)" | Out-File -FilePath $progressLog -Append -Encoding utf8
