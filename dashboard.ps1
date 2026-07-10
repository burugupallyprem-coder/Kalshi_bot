# stock-trader-bot mission control: pull latest data and open the dashboard
Set-Location $PSScriptRoot
git pull --rebase origin main
Invoke-Item "$PSScriptRoot\dashboard.html"
