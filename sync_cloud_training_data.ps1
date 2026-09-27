<#
  Hakee pilven kertyman uuden ennuste-/pisteytysdatan
  (cloud_export_training_data.yml -workflow'n kautta, GitHub CLI:lla),
  tuo sen paikalliseen kantaan, paivittaa training_matrix.csv:n (+ pysyva
  git-seurattu snapshot data/ml/challenger_residual_hgb_v1/-kansiossa),
  kouluttaa Challenger-mallin uudelleen, ja committaa/pushaa paivittyneet
  artefaktit GitHubiin.

  Tarkoitettu ajettavaksi Windowsin Task Schedulerista (esim. ti+la), mutta
  toimii identtisesti myos kasin ajettuna (tuplaklikkaa
  39_HAE_PILVIDATA_JA_KOULUTA.bat, tai aja se jo auki olevasta PowerShell-
  ikkunasta, jolloin ikkuna ei sulkeudu automaattisesti ajon paatyttya).

  Edellytykset koneella:
    - GitHub CLI (gh) asennettuna ja kirjautuneena ("gh auth login" kertaalleen)
    - .venv olemassa (katso 00_ASENNA.bat / 37_PAIVITA_ML_RIIPPUVUUDET.bat)

  HUOM: talla ei ole mitaan tekemista klo 6:15/16:15 ennusteajojen kanssa -
  ne ajaa pelkastaan pilvi (cloud_forecast.yml). Tama skripti vain hakee
  pilven kartuttaman datan paikalliseen mallinkehitykseen.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "sync_$stamp.log"

$pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Write-Log([string]$msg) {
    Write-Host $msg
}

# Windows PowerShell 5.1:n Start-Transcript ei aina poimi ulkoisten
# ohjelmien (python.exe, git.exe, gh.exe) suoraa konsolitulostetta
# luotettavasti - vain PowerShellin oman hostin kautta kirjoitetun
# tekstin. Tama apufunktio ajaa ulkoisen komennon, ohjaa sen koko
# tulosteen (stdout+stderr) PowerShellin oman pipelinen lapi ja
# kirjoittaa sen Write-Host:lla, jotta se varmasti paatyy lokiin. Palauttaa
# viimeisimman ulkoisen prosessin exit coden ($LASTEXITCODE), kuten
# suora kutsukin tekisi.
function Invoke-Logged {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][string[]]$Args
    )
    & $Exe @Args 2>&1 | ForEach-Object { Write-Host $_ }
    return $LASTEXITCODE
}

$exitCode = 0
Start-Transcript -Path $logPath -Append | Out-Null
try {
    Write-Log "=== PILVIDATAN HAKU JA MALLIN UUDELLEENKOULUTUS ($stamp) ==="

    if (-not (Test-Path $pythonExe)) {
        throw "Python-virtuaaliymparistoa ei loydy: $pythonExe"
    }

    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw "GitHub CLI (gh) ei loydy PATH:lta. Asenna: https://cli.github.com/ ja aja kertaalleen 'gh auth login'."
    }
    gh auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "gh ei ole kirjautuneena sisaan. Aja kasin: gh auth login"
    }

    Write-Log "`n--- 1/5: Kaynnistetaan cloud_export_training_data.yml ---"
    $before = [DateTimeOffset]::UtcNow
    if ((Invoke-Logged -Exe "gh" -Args @("workflow", "run", "cloud_export_training_data.yml")) -ne 0) {
        throw "Workflow'n kaynnistys epaonnistui (gh workflow run)."
    }

    $runId = $null
    for ($i = 0; $i -lt 24; $i++) {
        Start-Sleep -Seconds 5
        $runsJson = gh run list --workflow=cloud_export_training_data.yml --limit 5 --json databaseId,createdAt,event 2>$null
        if ($runsJson) {
            $runs = $runsJson | ConvertFrom-Json
            $candidate = $runs |
                Where-Object { $_.event -eq "workflow_dispatch" -and [DateTimeOffset]::Parse($_.createdAt) -ge $before.AddSeconds(-10) } |
                Sort-Object createdAt -Descending |
                Select-Object -First 1
            if ($candidate) { $runId = $candidate.databaseId; break }
        }
    }
    if (-not $runId) { throw "Uutta workflow-ajoa ei loytynyt 2 minuutin sisalla kaynnistyksesta." }
    Write-Log "Ajo loytyi (id $runId). Odotetaan valmistumista..."

    if ((Invoke-Logged -Exe "gh" -Args @("run", "watch", "$runId", "--exit-status")) -ne 0) {
        throw "Vienti-workflow epaonnistui (ajo $runId). Tarkista GitHub Actions -loki."
    }
    Write-Log "[OK] Vienti-workflow valmis."

    Write-Log "`n--- 2/5: Ladataan vienti levylle ---"
    $downloadDir = Join-Path $RepoRoot "lataukset\cloud_sync_$stamp"
    New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
    if ((Invoke-Logged -Exe "gh" -Args @("run", "download", "$runId", "-D", $downloadDir)) -ne 0) {
        throw "Artefaktin lataus epaonnistui (gh run download)."
    }

    $exportFile = Get-ChildItem -Path $downloadDir -Recurse -Filter "cloud_training_export.sqlite3" | Select-Object -First 1
    if (-not $exportFile) { throw "cloud_training_export.sqlite3 ei loytynyt ladatusta paketista ($downloadDir)." }
    Write-Log "Loytyi: $($exportFile.FullName)"

    Write-Log "`n--- 3/5: Tuodaan data paikalliseen kantaan (dedupe + merge + training_matrix) ---"
    if ((Invoke-Logged -Exe $pythonExe -Args @("scripts\import_cloud_training_data.py", "--export", $exportFile.FullName)) -ne 0) {
        throw "Tuontiskripti epaonnistui (import_cloud_training_data.py)."
    }

    Write-Log "`n--- 4/5: Koulutetaan Challenger-malli uudelleen ---"
    if ((Invoke-Logged -Exe $pythonExe -Args @("train_residual_challenger_v1.py")) -ne 0) {
        throw "Uudelleenkoulutus epaonnistui (train_residual_challenger_v1.py)."
    }

    Write-Log "`n--- 5/5: Committoidaan ja pushataan paivittyneet artefaktit ---"
    Invoke-Logged -Exe "git" -Args @("add", "data/ml/challenger_residual_hgb_v1/") | Out-Null
    $changes = git status --porcelain -- "data/ml/challenger_residual_hgb_v1/"
    if ([string]::IsNullOrWhiteSpace($changes)) {
        Write-Log "Ei muutoksia committoitavaksi (malli/data oli jo ajan tasalla)."
    } else {
        if ((Invoke-Logged -Exe "git" -Args @("commit", "-m", "Automated sync: refresh training data + Challenger model from cloud ($stamp)")) -ne 0) {
            throw "git commit epaonnistui."
        }
        if ((Invoke-Logged -Exe "git" -Args @("pull", "--no-rebase", "--no-edit")) -ne 0) {
            throw "git pull epaonnistui / yhdistamiskonflikti - vaatii kasin selvittamisen."
        }
        if ((Invoke-Logged -Exe "git" -Args @("push")) -ne 0) {
            throw "git push epaonnistui."
        }
        Write-Log "[OK] Muutokset pushattu GitHubiin."
    }

    # Ei-kriittinen siivous: poista yli 30 paivaa vanhat latauskansiot, jotta
    # 'lataukset' ei kasva loputtomiin.
    try {
        $cutoff = (Get-Date).AddDays(-30)
        Get-ChildItem -Path (Join-Path $RepoRoot "lataukset") -Directory -Filter "cloud_sync_*" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt $cutoff } |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Log "[VAROITUS] Vanhojen latauskansioiden siivous epaonnistui (ei kriittinen): $_"
    }

    Write-Log "`nVALMIS."
} catch {
    Write-Log "[VIRHE] $_"
    $exitCode = 1
} finally {
    Stop-Transcript | Out-Null
}
exit $exitCode
