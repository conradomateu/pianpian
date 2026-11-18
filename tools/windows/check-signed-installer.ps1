$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../..").Path
$destination = "$root/scratch/windows-signing/installed"
$setup = "$root/dist/Pianpian-Windows-Setup.exe"
$verify = "$PSScriptRoot/verify-signatures.ps1"
& $verify -Path $setup
if (Test-Path $destination) { throw 'Installer test requires an empty destination' }
$process = Start-Process -FilePath $setup -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
    '/SP-', "/DIR=`"$destination`"", "/LOG=`"$root/scratch/windows-signing/install.log`"") -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Installation failed: $($process.ExitCode)" }
python tools/windows_signing.py verify --installed $destination
if ($LASTEXITCODE -ne 0) { throw 'Installed payload differs from verified app' }
& $verify -Path @("$destination/Pianpian.exe", "$destination/_internal/pipeline/bin/pianpian-align.exe",
    "$destination/_internal/pipeline/bin/pianpian-sensevoice.exe",
    "$destination/_internal/pipeline/bin/pianpian-sensevoice-avx2.exe", "$destination/unins000.exe")
$process = Start-Process -FilePath "$destination/unins000.exe" -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Uninstallation failed: $($process.ExitCode)" }
if (Test-Path "$destination/Pianpian.exe") { throw 'Uninstallation left the app installed' }
Get-FileHash "$root/dist/Pianpian-Windows-Setup.exe", "$root/dist/Pianpian-Windows.zip" -Algorithm SHA256 |
    Select-Object @{Name='file';Expression={Split-Path $_.Path -Leaf}}, Hash |
    ConvertTo-Json | Set-Content "$root/dist/windows-signing-verification.json"
