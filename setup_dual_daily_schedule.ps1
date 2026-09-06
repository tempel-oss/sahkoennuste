param(
    [Parameter(Mandatory=$true)]
    [string]$ExistingTaskName,

    [string]$ExistingTaskPath = "\",

    [string]$MorningTaskSuffix = " - 06-15"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$archiveScript = Join-Path $projectRoot "archive_forecast_snapshot.py"

if (-not (Test-Path $pythonExe)) {
    throw "Python not found: $pythonExe"
}
if (-not (Test-Path $archiveScript)) {
    throw "Archive script not found: $archiveScript"
}

$task = Get-ScheduledTask `
    -TaskName $ExistingTaskName `
    -TaskPath $ExistingTaskPath `
    -ErrorAction Stop

$existingActions = @($task.Actions)

# Remove an earlier v1.5.7 archive action if this installer is rerun.
$filteredActions = @(
    $existingActions | Where-Object {
        -not (
            $_.Execute -eq $pythonExe -and
            $_.Arguments -match "archive_forecast_snapshot\.py"
        )
    }
)

$archiveAction = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument "`"$archiveScript`" --root `"$projectRoot`"" `
    -WorkingDirectory $projectRoot

$allActions = @($filteredActions) + @($archiveAction)

$afternoonTrigger = New-ScheduledTaskTrigger -Daily -At "16:15"
$morningTrigger = New-ScheduledTaskTrigger -Daily -At "06:15"

Write-Host "Updating existing task to 16:15 and enabling forecast archiving..."
Set-ScheduledTask `
    -TaskName $ExistingTaskName `
    -TaskPath $ExistingTaskPath `
    -Action $allActions `
    -Trigger $afternoonTrigger | Out-Null

$morningTaskName = "$ExistingTaskName$MorningTaskSuffix"

Write-Host "Creating morning task: $morningTaskName at 06:15..."
Register-ScheduledTask `
    -TaskName $morningTaskName `
    -TaskPath $ExistingTaskPath `
    -Action $allActions `
    -Trigger $morningTrigger `
    -Settings $task.Settings `
    -Principal $task.Principal `
    -Force | Out-Null

Write-Host ""
Write-Host "DUAL DAILY SCHEDULE INSTALLED"
Write-Host "Morning:   06:15  $ExistingTaskPath$morningTaskName"
Write-Host "Afternoon: 16:15  $ExistingTaskPath$ExistingTaskName"
Write-Host ""
Write-Host "Both runs use the same production actions."
Write-Host "After each run, latest_forecast.json is archived under:"
Write-Host "  data\forecast_archive\YYYY\MM\DD\"
