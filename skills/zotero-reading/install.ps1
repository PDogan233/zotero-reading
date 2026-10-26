param(
    [ValidateSet('Codex', 'ClaudeCode', 'DeepSeekHarness', 'Custom')]
    [string] $Client,
    [string] $Destination,
    [string] $BackupRoot,
    [switch] $OverwriteLocal
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $OutputEncoding
function Get-PackageHash([string] $Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}
$packageRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$manifestPath = Join-Path $packageRoot 'package-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Use the complete release ZIP, extracted first.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.name -ne 'zotero-reading' -or -not $manifest.files) { throw 'Invalid package manifest.' }
if (-not $Client -and -not $Destination) {
    [pscustomobject]@{ status = 'needs_install_target'; action = 'Identify the current Agent and pass -Client, or confirm its skill directory and pass -Destination. No default client is assumed.' } | ConvertTo-Json -Compress
    exit 2
}
if (-not $Client) { $Client = 'Custom' }
if ($Client -eq 'Custom' -and -not $Destination) {
    [pscustomobject]@{ status = 'needs_skill_directory'; action = 'Confirm the current Agent skill directory, then pass the full path ending in zotero-reading with -Destination.' } | ConvertTo-Json -Compress
    exit 2
}
if (-not $Destination) {
    $relative = '.agents\skills\zotero-reading'
    if ($Client -eq 'ClaudeCode') { $relative = '.claude\skills\zotero-reading' }
    if ($Client -eq 'DeepSeekHarness') {
        $dshConfigRoot = $env:DSH_HOME
        if (-not $dshConfigRoot) { $dshConfigRoot = Join-Path $env:USERPROFILE '.dsh' }
        $Destination = Join-Path $dshConfigRoot 'skills\zotero-reading'
    } else {
        $Destination = Join-Path $env:USERPROFILE $relative
    }
}
$target = [IO.Path]::GetFullPath($Destination)
if ([IO.Path]::GetFileName($target) -ne 'zotero-reading') { throw 'Destination must end with zotero-reading.' }
if ($target -eq $packageRoot) { throw 'Source and destination must differ.' }
if ($target.StartsWith($packageRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Destination cannot be inside the source package.'
}
# Refuse linked ancestors before any file operation.
$ancestor = $target
while ($ancestor) {
    if (Test-Path -LiteralPath $ancestor) {
        $entry = Get-Item -LiteralPath $ancestor -Force
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Choose a destination without directory links.' }
    }
    $ancestor = [IO.Path]::GetDirectoryName($ancestor)
}
$payload = @()
foreach ($property in $manifest.files.PSObject.Properties) {
    $name = $property.Name
    if ($name -match '(^[/\\]|[:\\]|(^|/)\.\.(/|$))') { throw 'Unsafe manifest path.' }
    $source = [IO.Path]::GetFullPath((Join-Path $packageRoot $name))
    $output = [IO.Path]::GetFullPath((Join-Path $target $name))
    if (-not $source.StartsWith($packageRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Source escaped package.' }
    if (-not $output.StartsWith($target + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Destination escaped skill.' }
    $entry = Get-Item -LiteralPath $source -Force
    if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked package files are not supported.' }
    if ((Get-PackageHash $source) -ne $property.Value) { throw ('Package checksum failed: ' + $name) }
    $payload += [pscustomobject]@{ Name = $name; Source = $source; Target = $output; Hash = $property.Value }
}
$installedManifest = Join-Path $target 'package-manifest.json'
$same = (Test-Path -LiteralPath $installedManifest) -and ((Get-PackageHash $installedManifest) -eq (Get-PackageHash $manifestPath))
if ($same) {
    foreach ($file in $payload) {
        if (-not (Test-Path -LiteralPath $file.Target) -or (Get-PackageHash $file.Target) -ne $file.Hash) { $same = $false; break }
    }
}
if ($same) {
    [pscustomobject]@{ status = 'already_installed'; client = $Client; path = $target; version = $manifest.version } | ConvertTo-Json -Compress
    exit 0
}
$backup = $null
if (Test-Path -LiteralPath $target) {
    $oldManifest = Join-Path $target 'package-manifest.json'
    if (-not (Test-Path -LiteralPath $oldManifest)) { throw 'Existing skill is not a managed installation. Back it up or choose another destination.' }
    $old = Get-Content -LiteralPath $oldManifest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($old.name -ne 'zotero-reading' -or -not $old.files) { throw 'Existing destination belongs to another skill or has an invalid manifest.' }
    # Additional files may be user edits. Preserve them in place and back up the whole directory.
    $linked = Get-ChildItem -LiteralPath $target -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
    if ($linked) { throw 'Existing skill contains links; review before upgrading.' }
    $localChanges = @()
    foreach ($property in $old.files.PSObject.Properties) {
        if ($property.Name -match '(^[/\\]|[:\\]|(^|/)\.\.(/|$))') { throw 'Unsafe path in existing manifest.' }
        $oldFile = Join-Path $target $property.Name
        if (-not (Test-Path -LiteralPath $oldFile -PathType Leaf)) {
            $localChanges += [pscustomobject]@{ path = $property.Name; kind = 'missing' }
        } elseif ((Get-PackageHash $oldFile) -ne $property.Value) {
            $localChanges += [pscustomobject]@{ path = $property.Name; kind = 'modified' }
        }
    }
    foreach ($file in $payload) {
        if (-not $old.files.PSObject.Properties[$file.Name] -and (Test-Path -LiteralPath $file.Target)) {
            $localChanges += [pscustomobject]@{ path = $file.Name; kind = 'unmanaged_collision' }
        }
    }
    if ($localChanges.Count -and -not $OverwriteLocal) {
        [pscustomobject]@{ status = 'local_changes'; path = $target; local_changes = $localChanges; action = 'Ask the recipient before overwriting. Only after explicit consent, repeat with -OverwriteLocal; the old files will be backed up.' } | ConvertTo-Json -Depth 5 -Compress
        exit 2
    }
    if (-not $BackupRoot) {
        if ($env:ZOTERO_READING_HOME) { $BackupRoot = Join-Path $env:ZOTERO_READING_HOME 'skill-backups' }
        else { $BackupRoot = Join-Path $env:LOCALAPPDATA 'ZoteroReading\skill-backups' }
    }
    $backupBase = [IO.Path]::GetFullPath($BackupRoot)
    if ($backupBase -eq $target -or $backupBase.StartsWith($target + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Backup must be outside the installed skill.' }
    $backup = Join-Path $backupBase ($Client + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Get-ChildItem -LiteralPath $target -Force | Copy-Item -Destination $backup -Recurse -Force
}
foreach ($file in $payload) {
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($file.Target)) -Force | Out-Null
    Copy-Item -LiteralPath $file.Source -Destination $file.Target -Force
}
Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $target 'package-manifest.json') -Force
[pscustomobject]@{ status = 'installed'; client = $Client; path = $target; version = $manifest.version; backup = $backup } | ConvertTo-Json -Compress
Write-Host 'Verify the installed SKILL.md and run run.ps1 setup. Refresh the Agent skill list or start a new chat if discovery has not updated.'
