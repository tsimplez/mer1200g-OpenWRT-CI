# MER1200G stock diagnostic SSH password, calculated locally.
# Use the LAN MAC shown on the router's stock web management page.
# Formula: lowercase MD5(uppercase MAC without separators), first 8 characters.
# No network access and no router changes.
[CmdletBinding()]
param(
    [string]$MacAddress
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($MacAddress)) {
    $MacAddress = Read-Host 'LAN MAC address (example: BC:54:FC:76:9E:2B)'
}

$normalized = ($MacAddress -replace '[-:.\s]', '').ToUpperInvariant()
if ($normalized -notmatch '\A[0-9A-F]{12}\z') {
    throw 'Invalid LAN MAC: expected exactly 12 hexadecimal digits, optionally separated by colon, hyphen, dot or spaces.'
}

$md5 = [System.Security.Cryptography.MD5]::Create()
try {
    $bytes = [System.Text.Encoding]::ASCII.GetBytes($normalized)
    $digest = $md5.ComputeHash($bytes)
    $hex = ([System.BitConverter]::ToString($digest) -replace '-', '').ToLowerInvariant()
    Write-Output $hex.Substring(0, 8)
}
finally {
    $md5.Dispose()
}
