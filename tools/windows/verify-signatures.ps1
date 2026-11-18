param(
    [Parameter(Mandatory)][string[]]$Path,
    [string]$ExpectedSubject = $env:WINDOWS_SIGNING_SUBJECT
)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ExpectedSubject)) { throw 'WINDOWS_SIGNING_SUBJECT is required' }
$signTool = Get-ChildItem "${env:ProgramFiles(x86)}/Windows Kits/10/bin/*/x64/signtool.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1
if (!$signTool) { throw 'Windows SDK signtool.exe is required' }
foreach ($item in $Path) {
    $file = Get-Item -LiteralPath $item
    $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
    if ($signature.Status -ne 'Valid' -or $signature.SignatureType -ne 'Authenticode') {
        throw "Invalid embedded Authenticode signature: $item ($($signature.Status))"
    }
    if ($signature.SignerCertificate.Subject -cne $ExpectedSubject) { throw "Unexpected publisher: $item" }
    if (!$signature.TimeStamperCertificate) { throw "Missing timestamp: $item" }
    # /tw makes a missing timestamp a warning; treating every nonzero exit as failure makes it mandatory.
    & $signTool.FullName verify /pa /all /tw $file.FullName
    if ($LASTEXITCODE -ne 0) { throw "SignTool trust/timestamp verification failed: $item" }
    [pscustomobject]@{
        file = $file.Name
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
        publisher = $signature.SignerCertificate.Subject
        certificate = $signature.SignerCertificate.Thumbprint
        timestampCertificate = $signature.TimeStamperCertificate.Thumbprint
    } | ConvertTo-Json -Compress | Write-Host
}
