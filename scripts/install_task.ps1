
param(
  [string]$Time = "16:15",
  [string]$TaskName = "Electricity Forecaster Daily"
)
$ErrorActionPreference="Stop"
$Project=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Bat=Join-Path $Project "21_AJA_KAIKKI.bat"
if (!(Test-Path $Bat)) { throw "21_AJA_KAIKKI.bat puuttuu." }

$parts=$Time.Split(":")
if ($parts.Count -ne 2) { throw "Aika muodossa HH:MM, esim. 16:15." }
$trigger=New-ScheduledTaskTrigger -Daily -At $Time
$action=New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Bat`"" -WorkingDirectory $Project
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Paivittainen FI-sahkohintaennuste D+2...D+12" -Force | Out-Null
Write-Host "[OK] Tehtava asennettu: $TaskName"
Write-Host "Ajo joka paiva klo $Time."
Write-Host "Huom: koneen tulee olla kaynnissa. StartWhenAvailable ajaa tehtavan myohemmin, jos ajankohta meni ohi."
