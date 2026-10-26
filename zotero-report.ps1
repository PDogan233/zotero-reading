param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $ReportArguments
)

# Compatible with Windows PowerShell 5.1. Do not depend on a developer's PATH.
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $OutputEncoding
$reportCandidates = @()
if ($env:ZOTERO_READING_PYTHON) { $reportCandidates += $env:ZOTERO_READING_PYTHON }
$reportCandidates += (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
foreach ($reportName in @('python', 'python3', 'py')) {
    $reportCommand = Get-Command $reportName -ErrorAction SilentlyContinue
    if ($reportCommand) { $reportCandidates += $reportCommand.Source }
}
$reportCandidates += @(Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe') -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
$reportPythonExecutable = $null
$reportPythonPrefix = @()
foreach ($reportCandidate in ($reportCandidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $reportCandidate)) { continue }
    if ($reportCandidate -like '*\WindowsApps\*') { continue }
    $reportPrefix = @()
    if ([IO.Path]::GetFileName($reportCandidate) -eq 'py.exe') { $reportPrefix = @('-3') }
    try {
        $reportVersion = & $reportCandidate @reportPrefix -c 'import sys; print(int(sys.version_info >= (3,10)))' 2>$null
        if ($LASTEXITCODE -eq 0 -and $reportVersion -eq '1') {
            $reportPythonExecutable = $reportCandidate
            $reportPythonPrefix = $reportPrefix
            break
        }
    } catch { continue }
}
if (-not $reportPythonExecutable) {
    Write-Output '{"status":"python_required","action":"Install Python 3.10+ from https://www.python.org/downloads/windows/ or set ZOTERO_READING_PYTHON to an existing python.exe. Then retry the same request."}'
    exit 2
}
$reportEntryPoint = Join-Path $PSScriptRoot 'scripts\bootstrap.py'
$reportBytecodeOptions = @()
if ($ReportArguments -contains 'skill-update') { $reportBytecodeOptions = @('-B') }
& $reportPythonExecutable @reportPythonPrefix @reportBytecodeOptions -X utf8 $reportEntryPoint @ReportArguments
exit $LASTEXITCODE
