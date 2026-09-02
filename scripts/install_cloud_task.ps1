
param([string]$Time="16:15",[string]$TaskName="Electricity Forecaster Daily Publish")
$Project=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Bat=Join-Path $Project "30_AJA_JA_JULKAISE.bat"
$trigger=New-ScheduledTaskTrigger -Daily -At $Time
$action=New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Bat`"" -WorkingDirectory $Project
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Paivittainen sahkoennuste + GitHub Pages" -Force | Out-Null
Write-Host "[OK] Paivittainen julkaisu asennettu klo $Time."
