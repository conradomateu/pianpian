# CI only: a disposable, non-exportable certificate exercises the real Windows APIs and installer.
# This certificate is trusted only by this runner, never by users. No private key is exported.
$ErrorActionPreference = 'Stop'
$signTool = Get-ChildItem "${env:ProgramFiles(x86)}/Windows Kits/10/bin/*/x64/signtool.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1
if (!$signTool) { throw 'Windows SDK signtool.exe is required' }
$verify = "$PSScriptRoot/verify-signatures.ps1"
$testRoot = 'scratch/windows-signing-test'
New-Item -ItemType Directory -Force $testRoot | Out-Null
Write-Host 'Creating disposable code-signing certificate'
$certificate = New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN=Pianpian CI ONLY - NOT FOR DISTRIBUTION' `
    -CertStoreLocation Cert:/CurrentUser/My -KeyExportPolicy NonExportable -HashAlgorithm SHA256 `
    -NotAfter (Get-Date).AddDays(1)
$env:WINDOWS_SIGNING_SUBJECT = $certificate.Subject
function Sign-Fixture([string]$File, [bool]$Timestamp = $true) {
    $arguments = @('sign', '/sha1', $certificate.Thumbprint, '/fd', 'SHA256')
    if ($Timestamp) { $arguments += @('/tr', 'http://timestamp.digicert.com', '/td', 'SHA256') }
    Write-Host "Signing fixture: $File (timestamp=$Timestamp)"
    & $signTool.FullName @arguments $File
    if ($LASTEXITCODE -ne 0) { throw "Fixture signing failed: $File" }
}
function Expect-Rejected([string]$File, [string]$Subject = $certificate.Subject) {
    $rejected = $false
    try { & $verify -Path $File -ExpectedSubject $Subject } catch { $rejected = $true }
    if (!$rejected) { throw "Verifier incorrectly accepted $File" }
}
try {
    # CurrentUser Root insertion shows a consent dialog; this disposable runner is already elevated.
    Write-Host 'Trusting fixture certificate on this disposable runner'
    $store = [System.Security.Cryptography.X509Certificates.X509Store]::new('Root', 'LocalMachine')
    $store.Open('ReadWrite')
    $store.Add($certificate)
    $store.Close()
    Write-Host 'Staging fixture executables'
    python tools/windows_signing.py prepare
    if ($LASTEXITCODE -ne 0) { throw 'Staging failed' }
    $source = 'scratch/windows-signing/unsigned/Pianpian.exe'
    Copy-Item $source "$testRoot/unsigned.exe"
    Expect-Rejected "$testRoot/unsigned.exe"
    Copy-Item $source "$testRoot/no-timestamp.exe"
    Sign-Fixture "$testRoot/no-timestamp.exe" $false
    Expect-Rejected "$testRoot/no-timestamp.exe"
    Copy-Item $source "$testRoot/valid.exe"
    Sign-Fixture "$testRoot/valid.exe"
    & $verify -Path "$testRoot/valid.exe"
    Expect-Rejected "$testRoot/valid.exe" 'CN=Wrong publisher'
    Copy-Item "$testRoot/valid.exe" "$testRoot/tampered.exe"
    $bytes = [IO.File]::ReadAllBytes("$testRoot/tampered.exe")
    $bytes[100] = $bytes[100] -bxor 1
    [IO.File]::WriteAllBytes("$testRoot/tampered.exe", $bytes)
    Expect-Rejected "$testRoot/tampered.exe"
    Copy-Item scratch/windows-signing/unsigned scratch/windows-signing/signed -Recurse
    $version = (Get-Content .release-please-manifest.json | ConvertFrom-Json).'.'
    foreach ($file in Get-ChildItem scratch/windows-signing/signed/*.exe) {
        # Inno preserves fixed-width VERSIONINFO fields, padded with spaces.
        if ($file.VersionInfo.ProductName.Trim() -ne 'Pianpian' -or $file.VersionInfo.ProductVersion.Trim() -ne $version) {
            throw "Unexpected metadata for $($file.Name): product='$($file.VersionInfo.ProductName)', version='$($file.VersionInfo.ProductVersion)'"
        }
        Sign-Fixture $file.FullName
        & $verify -Path $file.FullName
    }
    python tools/windows_signing.py apply
    if ($LASTEXITCODE -ne 0) { throw 'Signed payload restoration failed' }
    python tools/build_app_windows.py --package-signed
    if ($LASTEXITCODE -ne 0) { throw 'Signed packaging failed' }
    Sign-Fixture 'dist/Pianpian-Windows-Setup.exe'
    & "$PSScriptRoot/check-signed-installer.ps1"
    Write-Host 'PASS: real Authenticode rejection cases, metadata, timestamps, install/payload verification and uninstall'
} finally {
    Remove-Item "Cert:/LocalMachine/Root/$($certificate.Thumbprint)" -ErrorAction SilentlyContinue
    Remove-Item "Cert:/CurrentUser/My/$($certificate.Thumbprint)" -DeleteKey -ErrorAction SilentlyContinue
}
