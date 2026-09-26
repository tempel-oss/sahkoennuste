param(
  [ValidateSet("morning","afternoon")]
  [string]$ExpectedSlot
)

$ErrorActionPreference = "Stop"
$j = Get-Content .\output\latest_forecast.json -Raw | ConvertFrom-Json
Write-Host "issue_slot:" $j.issue_slot
Write-Host ""
Write-Host "Published day-ahead:"
$j.published_day_ahead | Select-Object d_plus,value_type,published,date | Format-Table -AutoSize
Write-Host "Forecast:"
$j.days | Select-Object d_plus,value_type,date | Format-Table -AutoSize

if ($ExpectedSlot) {
  if ($j.issue_slot -ne $ExpectedSlot) { throw "Expected issue_slot=$ExpectedSlot, got $($j.issue_slot)" }
  if ($ExpectedSlot -eq "morning") {
    $expectedForecast = @(1..11); $expectedPublished = @(0)
  } else {
    $expectedForecast = @(2..12); $expectedPublished = @(0,1)
  }
  $gotForecast = @($j.days | ForEach-Object { [int]$_.d_plus })
  $gotPublished = @($j.published_day_ahead | ForEach-Object { [int]$_.d_plus })
  if (Compare-Object $expectedForecast $gotForecast) { throw "Forecast horizons do not match expected $ExpectedSlot layout" }
  if (Compare-Object $expectedPublished $gotPublished) { throw "Published horizons do not match expected $ExpectedSlot layout" }
  if (@($j.days | Where-Object { $_.value_type -ne "forecast" }).Count -gt 0) { throw "Forecast value_type verification failed" }
  if (@($j.published_day_ahead | Where-Object { $_.value_type -ne "day_ahead" }).Count -gt 0) { throw "Day-ahead value_type verification failed" }
  Write-Host ""
  Write-Host "[OK] $ExpectedSlot JSON layout verified."
}
