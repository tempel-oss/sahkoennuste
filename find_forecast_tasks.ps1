$ErrorActionPreference = "Stop"

Write-Host "Scheduled tasks that may belong to Electricity Forecaster:"
Write-Host ""

$rows = foreach ($task in Get-ScheduledTask) {
    $actions = @($task.Actions)
    $actionText = ($actions | ForEach-Object {
        "$($_.Execute) $($_.Arguments) $($_.WorkingDirectory)"
    }) -join " ; "

    if (
        $task.TaskName -match "electric|forecast|sahko|ennuste" -or
        $actionText -match "electricity_forecaster|forecast|sahko|ennuste"
    ) {
        $triggers = @($task.Triggers) | ForEach-Object {
            $_.StartBoundary
        }

        [PSCustomObject]@{
            TaskName = $task.TaskName
            TaskPath = $task.TaskPath
            State = $task.State
            Triggers = ($triggers -join " ; ")
            Actions = $actionText
        }
    }
}

if (-not $rows) {
    Write-Host "No obvious forecast tasks found."
    Write-Host "Open Task Scheduler and check the exact task name."
    exit 1
}

$rows | Format-List
