$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$localCli = Join-Path $projectRoot '.tools\aws-cli\Amazon\AWSCLIV2\aws.exe'
if (Test-Path -LiteralPath $localCli) {
    & $localCli @args
} else {
    $installedCli = Get-Command aws.exe -ErrorAction SilentlyContinue
    if (-not $installedCli) { throw 'Install AWS CLI v2 from aws.amazon.com/cli, then retry.' }
    & $installedCli.Source @args
}
exit $LASTEXITCODE
