<#
Laukaisee cloud_forecast.yml-workflown GitHubissa workflow_dispatch-tapahtumana.

Tausta (ks. loydokset_ja_korjaukset.md, kohta Q): GitHubin oma schedule/cron-
ajastus on 3.10.2026 iltapaivasta lahtien laukaissut cloud_forecast.yml:n
4-7 tuntia myohassa joka ainoalla ajolla - tama on GitHubin oma, tunnettu ja
kirjoitushetkella korjaamaton infrastruktuurivika (ei mitaan tekemista taman
repon koodin kanssa), eika sita voi korjata workflow-tiedoston cron-
lausekkeita muuttamalla.

Tama skripti on tarkoitus ajastaa Windows Task Schedulerilla klo 6:15 ja
16:15 Suomen aikaa (ks. Register-ScheduledTask-ohjeet dokumentaatiossa) -
paikallinen, luotettava laukaisin GitHubin oman rikkinaisen cronin rinnalle.
scripts/cloud_gate.py on paivitetty (ks. sama kohta Q) estamaan samalle
paivalle/slotille tuleva kaksoisjulkaisu, jos GitHubin oma myohastynyt cron
silti laukeaa myohemmin samana paivana.

Noudattaa N-kohdan opetusta: $ErrorActionPreference="Stop" + 2>&1-putki
ulkoisen komennon (gh.exe) ympärilla voi tulkita harmittoman stderr-rivin
virheeksi - sen takia Invoke-Logged asettaa ErrorActionPreferencen paikallisesti
"Continue"-tilaan juuri ulkoisen komennon ajon ajaksi ja luottaa yksinomaan
$LASTEXITCODE:iin.
#>

param(
    [ValidateSet('morning','afternoon')]
    [string]$Slot
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

if (-not $Slot) {
    $now = Get-Date
    if ($now.Hour -lt 12) { $Slot = 'morning' } else { $Slot = 'afternoon' }
}
Set-Location $root

$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "trigger_$ts.log"
Start-Transcript -Path $logFile -Force | Out-Null

function Invoke-Logged {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][string[]]$Args
    )
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @Args 2>&1 | ForEach-Object { Write-Host $_ }
    } finally {
        $ErrorActionPreference = $previousEap
    }
    return $LASTEXITCODE
}

try {
    Write-Host "=== LAUKAISTAAN PILVIENNUSTE-WORKFLOW ($ts), slot=$Slot ==="
    $exit = Invoke-Logged -Exe 'gh' -Args @('workflow','run','cloud_forecast.yml','--ref','main','-f',"slot=$Slot")
    if ($exit -ne 0) {
        throw "gh workflow run epaonnistui (exit code $exit)"
    }
    Write-Host "[OK] Workflow laukaistu onnistuneesti. (slot=$Slot; cloud_gate.py ohittaa ajon, jos taman paivan sama slotti on jo julkaistu.)"
    exit 0
} catch {
    Write-Host "[VIRHE] $($_.Exception.Message)"
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
