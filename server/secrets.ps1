param([ValidateSet('protect','unprotect')][string]$Action)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
$payload = [Console]::In.ReadToEnd().Trim()
$bytes = [Convert]::FromBase64String($payload)
$entropy = [Text.Encoding]::UTF8.GetBytes('FYPPPPP.local.v1')
if ($Action -eq 'protect') {
  $result = [Security.Cryptography.ProtectedData]::Protect($bytes, $entropy, [Security.Cryptography.DataProtectionScope]::CurrentUser)
} else {
  $result = [Security.Cryptography.ProtectedData]::Unprotect($bytes, $entropy, [Security.Cryptography.DataProtectionScope]::CurrentUser)
}
[Console]::Out.Write([Convert]::ToBase64String($result))
