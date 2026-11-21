@echo off
setlocal
chcp 65001 >nul
set "MER1200G_LAUNCHER_FILE=%~f0"
set "MER1200G_LAUNCHER_MODE=%~1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$text = Get-Content -LiteralPath $env:MER1200G_LAUNCHER_FILE -Raw -Encoding UTF8; $parts = $text -split '(?m)^# MER1200G_POWERSHELL_BEGIN\r?$', 2; if ($parts.Count -ne 2) { throw 'Launcher body missing' }; & ([scriptblock]::Create($parts[1]))"
exit /b %errorlevel%
# MER1200G_POWERSHELL_BEGIN
# This launcher uses the published installer without changing its safety gates.
# Default: interactive installation. Argument "verify": local checks only.
$ErrorActionPreference = 'Stop'
$taskVerifyOnly = $env:MER1200G_LAUNCHER_MODE -eq 'verify'
$taskParentWindow = $false
$taskSucceeded = $false
$taskOwnInstall = $false
$taskExitCode = 1
$taskStockCompatibility = @'
import getpass, inspect, re, runpy, sys
arguments = sys.argv[1:]
package = arguments[0]
sys.path.insert(0, package)
import bootstrap
# Adapt the published package to vendor BusyBox without changing its firmware,
# backup binding, geometry policy, or native preflight/flash checks.
original_command = bootstrap.DEVICE_COMMAND
stat_fragment = 'stat -c ' + chr(39) + '%t %T' + chr(39) + ' /dev/mtd9 && '
assert original_command.count(stat_fragment) == 1, 'Unknown stock geometry command'
bootstrap.DEVICE_COMMAND = original_command.replace(stat_fragment, 'LC_ALL=C ls -ln /dev/mtd9 && ')
original_geometry = bootstrap.parse_geometry
def vendor_geometry(data):
    lines = data.decode('ascii').strip().splitlines()
    assert len(lines) == 6, 'Missing stock NOR device geometry'
    match = re.fullmatch(r'c[rwxstST-]{9}\s+\d+\s+\d+\s+\d+\s+(\d+),\s+(\d+)\s+.+\s+/dev/mtd9', lines[0])
    assert match is not None, 'Invalid stock MTD character-device listing'
    lines[0] = '%x %x' % tuple(int(value, 10) for value in match.groups())
    return original_geometry(('\n'.join(lines) + '\n').encode('ascii'))
bootstrap.parse_geometry = vendor_geometry
# Connection adapters resolve the wired MAC after TCP establishes ARP.
# Encode only these reviewed functions to preserve quotes through Windows PowerShell.
import controller
exec(compile(bootstrap.base64.b64decode('ZGVmIHN0b2NrX3Bhc3N3b3JkKGluZGV4PU5vbmUpOgogICAgIiIiQ2FsY3VsYXRlIHRoZSBzdG9jayBkaWFnbm9zdGljIHBhc3N3b3JkIGZyb20gdGhlIGJvdW5kIHdpcmVkIG5laWdoYm9yLgoKICAgIE1BQyBhbmQgcGFzc3dvcmQgc3RheSBpbiBtZW1vcnkuIFNTSCBob3N0LWtleSBhY2NlcHRhbmNlIHN0aWxsIHByZWNlZGVzCiAgICBhdXRoZW50aWNhdGlvbjsgYW4gYWJzZW50IG9yIGFtYmlndW91cyBuZWlnaGJvciBuZXZlciBwZXJtaXRzIGd1ZXNzaW5nLgogICAgIiIiCiAgICBpZiBpbmRleCBpcyBOb25lOgogICAgICAgIHZhbHVlID0gZ2V0cGFzcy5nZXRwYXNzKCJTdG9jayByb290IFNTSCBwYXNzd29yZDogIikKICAgICAgICByZXF1aXJlKHZhbHVlLCAiU3RvY2sgU1NIIHBhc3N3b3JkIGlzIGVtcHR5OyBubyByb3V0ZXIgY29ubmVjdGlvbiBhdHRlbXB0ZWQiKQogICAgICAgIHJldHVybiB2YWx1ZQogICAgcmVxdWlyZSh0eXBlKGluZGV4KSBpcyBpbnQgYW5kIGluZGV4ID4gMCwgIkludmFsaWQgd2lyZWQgaW50ZXJmYWNlIGluZGV4IikKICAgIHNjcmlwdCA9ICgKICAgICAgICAiR2V0LU5ldE5laWdoYm9yIC1JbnRlcmZhY2VJbmRleCAiICsgc3RyKGluZGV4KSArCiAgICAgICAgIiAtQWRkcmVzc0ZhbWlseSBJUHY0IC1JUEFkZHJlc3MgIiArIEhPU1QgKwogICAgICAgICIgLUVycm9yQWN0aW9uIFN0b3AgfCBTZWxlY3QtT2JqZWN0IElQQWRkcmVzcyxJbnRlcmZhY2VJbmRleCxMaW5rTGF5ZXJBZGRyZXNzLCIKICAgICAgICAiQHtOYW1lPSdTdGF0ZSc7RXhwcmVzc2lvbj17W3N0cmluZ10kXy5TdGF0ZX19IHwgQ29udmVydFRvLUpzb24gLUNvbXByZXNzIikKICAgIHJvd3MgPSBqc29uLmxvYWRzKHN1YnByb2Nlc3MuY2hlY2tfb3V0cHV0KAogICAgICAgIFsicG93ZXJzaGVsbC5leGUiLCAiLU5vUHJvZmlsZSIsICItQ29tbWFuZCIsIHNjcmlwdF0pKQogICAgcm93cyA9IFtyb3dzXSBpZiBpc2luc3RhbmNlKHJvd3MsIGRpY3QpIGVsc2Ugcm93cwogICAgcmVxdWlyZShpc2luc3RhbmNlKHJvd3MsIGxpc3QpIGFuZCBsZW4ocm93cykgPT0gMSwKICAgICAgICAgICAgIk5lZWQgb25lIHN0b2NrIHJvdXRlciBuZWlnaGJvciBvbiB0aGUgd2lyZWQgYWRhcHRlcjsgb3BlbiBpdHMgc3RvY2sgd2ViIFVJIGZpcnN0IikKICAgIHJvdyA9IHJvd3NbMF0KICAgIHJlcXVpcmUoaXNpbnN0YW5jZShyb3csIGRpY3QpIGFuZCByb3cuZ2V0KCJJUEFkZHJlc3MiKSA9PSBIT1NUIGFuZAogICAgICAgICAgICByb3cuZ2V0KCJJbnRlcmZhY2VJbmRleCIpID09IGluZGV4IGFuZAogICAgICAgICAgICByb3cuZ2V0KCJTdGF0ZSIpIGluIHsiUmVhY2hhYmxlIiwgIlN0YWxlIiwgIkRlbGF5IiwgIlByb2JlIiwgIlBlcm1hbmVudCJ9LAogICAgICAgICAgICAiU3RvY2sgcm91dGVyIG5laWdoYm9yIGRvZXMgbm90IG1hdGNoIHRoZSB3aXJlZCBpbnRlcmZhY2UiKQogICAgbWFjID0gcm93LmdldCgiTGlua0xheWVyQWRkcmVzcyIsICIiKQogICAgcmVxdWlyZShpc2luc3RhbmNlKG1hYywgc3RyKSBhbmQKICAgICAgICAgICAgcmUuZnVsbG1hdGNoKHIiWzAtOUEtRmEtZl17Mn0oPzotWzAtOUEtRmEtZl17Mn0pezV9IiwgbWFjKSBpcyBub3QgTm9uZSwKICAgICAgICAgICAgIkludmFsaWQgc3RvY2sgTEFOIE1BQyBpbiB0aGUgd2lyZWQgbmVpZ2hib3IgdGFibGUiKQogICAgbm9ybWFsaXplZCA9IG1hYy5yZXBsYWNlKCItIiwgIiIpLnVwcGVyKCkKICAgIHJlcXVpcmUobm9ybWFsaXplZCAhPSAiMDAwMDAwMDAwMDAwIiBhbmQgbm90IChpbnQobm9ybWFsaXplZFs6Ml0sIDE2KSAmIDEpLAogICAgICAgICAgICAiU3RvY2sgTEFOIE1BQyBtdXN0IGJlIGEgbm9uemVybyB1bmljYXN0IGFkZHJlc3MiKQogICAgcHJpbnQoIlN0b2NrIGRpYWdub3N0aWMgcGFzc3dvcmQ6IGF1dG8gZnJvbSB3aXJlZCBMQU4gTUFDICIgKyBtYWMudXBwZXIoKSArCiAgICAgICAgICAiOyBwYXNzd29yZCBub3Qgc2F2ZWQiLCBmbHVzaD1UcnVlKQogICAgcmV0dXJuIGhhc2hsaWIubWQ1KG5vcm1hbGl6ZWQuZW5jb2RlKCJhc2NpaSIpKS5oZXhkaWdlc3QoKVs6OF0KCmRlZiBjb25uZWN0X3N0b2NrKHdvcmtkaXIsIGhvc3Q9SE9TVCk6CiAgICAiIiJUcnVzdCBvbmUgZXhwbGljaXRseSBhY2NlcHRlZCwgZGlyZWN0bHkgY29ubmVjdGVkIHN0b2NrIFNTSCBzZXJ2ZXIuCgogICAgUGFzc3dvcmRzIG5ldmVyIGVudGVyIGZpbGVzIG9yIGNvbW1hbmQgYXJndW1lbnRzLiBUaGUgYWNjZXB0ZWQga2V5IGlzIG5vdAogICAgcGVyc2lzdGVkIHVudGlsIGNvbGxlY3Rfc3RvY2sgaGFzIHZlcmlmaWVkIGFuZCBzYXZlZCB0aGUgbmV3IGJhY2t1cC4KICAgICIiIgogICAgZGVsIHdvcmtkaXIgICMgTm8gZmlsZXMgYXJlIGNoYW5nZWQgYnkgdGhlIGNvbm5lY3Rpb24gYXR0ZW1wdC4KICAgIHJlcXVpcmUoaG9zdCA9PSBIT1NULCAiVGhpcyBidWlsZCByZXF1aXJlcyBzdG9jayBMQU4gYWRkcmVzcyAiICsgSE9TVCkKICAgIGltcG9ydCBwYXJhbWlrbwoKICAgIGNsaWVudCA9IHBhcmFtaWtvLlNTSENsaWVudCgpCiAgICBhY2NlcHRlZCA9IHt9CgogICAgY2xhc3MgRmlyc3RDb25uZWN0aW9uKHBhcmFtaWtvLk1pc3NpbmdIb3N0S2V5UG9saWN5KToKICAgICAgICBkZWYgbWlzc2luZ19ob3N0X2tleShzZWxmLCBzc2gsIGhvc3RuYW1lLCBrZXkpOgogICAgICAgICAgICB2YWx1ZSA9IGZpbmdlcnByaW50KGtleSkKICAgICAgICAgICAgcHJpbnQoIk5ldyBzdG9jayBTU0ggaG9zdCBmaW5nZXJwcmludDogU0hBMjU2OiIgKyB2YWx1ZSwgZmx1c2g9VHJ1ZSkKICAgICAgICAgICAgcmVxdWlyZShpbnB1dCgiVHJ1c3QgdGhpcyBkaXJlY3RseSBjb25uZWN0ZWQgbmV3IHJvdXRlcj8gVHlwZSB5ZXM6ICIpLnN0cmlwKCkgPT0gInllcyIsCiAgICAgICAgICAgICAgICAgICAgIk5ldyByb3V0ZXIgaG9zdCBrZXkgd2FzIG5vdCBhY2NlcHRlZCIpCiAgICAgICAgICAgIGFjY2VwdGVkWyJmaW5nZXJwcmludCJdID0gdmFsdWUKICAgICAgICAgICAgc3NoLmdldF9ob3N0X2tleXMoKS5hZGQoaG9zdG5hbWUsIGtleS5nZXRfbmFtZSgpLCBrZXkpCgogICAgY2xpZW50LnNldF9taXNzaW5nX2hvc3Rfa2V5X3BvbGljeShGaXJzdENvbm5lY3Rpb24oKSkKICAgIGluZGV4ID0gd2luZG93c19pbmRleCgpCiAgICBwYXNzd29yZCA9IHN0b2NrX3Bhc3N3b3JkKCkgaWYgaW5kZXggaXMgTm9uZSBlbHNlIE5vbmUKICAgIHNvY2sgPSBzb2NrZXQuc29ja2V0KCkKICAgIHNvY2suc2V0dGltZW91dCgxNSkKICAgIHRyeToKICAgICAgICBpZiBpbmRleCBpcyBub3QgTm9uZToKICAgICAgICAgICAgc29jay5zZXRzb2Nrb3B0KHNvY2tldC5JUFBST1RPX0lQLCAzMSwgc3RydWN0LnBhY2soIiFJIiwgaW5kZXgpKQogICAgICAgIHNvY2suYmluZCgoUENfQUREUkVTUywgMCkpCiAgICAgICAgc29jay5jb25uZWN0KChob3N0LCBTU0hfUE9SVCkpCiAgICAgICAgIyBBIGZyZXNoIG5ldHdvcmsgcHJlcGFyYXRpb24gY2xlYXJzIEFSUC4gVGhpcyBib3VuZCBUQ1AgY29ubmVjdGlvbgogICAgICAgICMgcmVzb2x2ZXMgdGhlIGN1cnJlbnQgcm91dGVyIE1BQyBiZWZvcmUgdGhlIG5laWdoYm9yLXRhYmxlIGxvb2t1cC4KICAgICAgICBpZiBpbmRleCBpcyBub3QgTm9uZToKICAgICAgICAgICAgcGFzc3dvcmQgPSBzdG9ja19wYXNzd29yZChpbmRleCkKICAgICAgICBjbGllbnQuY29ubmVjdChob3N0LCBwb3J0PVNTSF9QT1JULCB1c2VybmFtZT0icm9vdCIsIHBhc3N3b3JkPXBhc3N3b3JkLAogICAgICAgICAgICAgICAgICAgICAgIHNvY2s9c29jaywgYWxsb3dfYWdlbnQ9RmFsc2UsIGxvb2tfZm9yX2tleXM9RmFsc2UsCiAgICAgICAgICAgICAgICAgICAgICAgdGltZW91dD0xNSwgYmFubmVyX3RpbWVvdXQ9MTUsIGF1dGhfdGltZW91dD0yMCkKICAgICAgICB0cmFuc3BvcnQgPSBjbGllbnQuZ2V0X3RyYW5zcG9ydCgpCiAgICAgICAgcmVxdWlyZSh0cmFuc3BvcnQgaXMgbm90IE5vbmUgYW5kIHRyYW5zcG9ydC5pc19hdXRoZW50aWNhdGVkKCksCiAgICAgICAgICAgICAgICAiU3RvY2sgU1NIIGlzIG5vdCBhdXRoZW50aWNhdGVkIikKICAgICAgICByZXF1aXJlKGFjY2VwdGVkLmdldCgiZmluZ2VycHJpbnQiKSA9PSBmaW5nZXJwcmludCh0cmFuc3BvcnQuZ2V0X3JlbW90ZV9zZXJ2ZXJfa2V5KCkpLAogICAgICAgICAgICAgICAgIkF1dGhlbnRpY2F0ZWQgc3RvY2sgaG9zdCBrZXkgZGlmZmVycyBmcm9tIHRoZSBleHBsaWNpdGx5IGFjY2VwdGVkIGtleSIpCiAgICAgICAgcmV0dXJuIGNsaWVudAogICAgZXhjZXB0IEJhc2VFeGNlcHRpb246CiAgICAgICAgY2xpZW50LmNsb3NlKCkKICAgICAgICBzb2NrLmNsb3NlKCkKICAgICAgICByYWlzZQogICAgZmluYWxseToKICAgICAgICBwYXNzd29yZCA9IE5vbmU='), '<wired-ssh-connection>', 'exec'), bootstrap.__dict__)
exec(compile(bootstrap.base64.b64decode('ZGVmIGNvbm5lY3QoYnVuZGxlLCBuYXRpdmU9RmFsc2UpOgogICAgaW1wb3J0IHBhcmFtaWtvCiAgICBmcm9tIGJvb3RzdHJhcCBpbXBvcnQgc3RvY2tfcGFzc3dvcmQKICAgIGNsaWVudD1wYXJhbWlrby5TU0hDbGllbnQoKTtrbm93bj1idW5kbGUvKCdrbm93bl9ob3N0c19uYXRpdmUnIGlmIG5hdGl2ZSBlbHNlICdrbm93bl9ob3N0cycpCiAgICBleHBlY3RlZD1Ob25lIGlmIG5hdGl2ZSBlbHNlIHN0b2NrX2ZpbmdlcnByaW50KGJ1bmRsZSkKICAgIHJvdXRlcl9pcHY0LHBjX2lwdjQscG9ydD1zc2hfZW5kcG9pbnQobmF0aXZlKQogICAgaWYga25vd24uZXhpc3RzKCk6Y2xpZW50LmxvYWRfaG9zdF9rZXlzKHN0cihrbm93bikpCiAgICBjbGFzcyBGaXJzdENvbm5lY3Rpb24ocGFyYW1pa28uTWlzc2luZ0hvc3RLZXlQb2xpY3kpOgogICAgICAgIGRlZiBtaXNzaW5nX2hvc3Rfa2V5KHNlbGYsc3NoLGhvc3RuYW1lLGtleSk6CiAgICAgICAgICAgIGZpbmdlcnByaW50PWJhc2U2NC5iNjRlbmNvZGUoaGFzaGxpYi5zaGEyNTYoa2V5LmFzYnl0ZXMoKSkuZGlnZXN0KCkpLmRlY29kZSgpLnJzdHJpcCgnPScpCiAgICAgICAgICAgIHByaW50KCgnTmF0aXZlJyBpZiBuYXRpdmUgZWxzZSAnU3RvY2snKSsnIFNTSCBob3N0IGZpbmdlcnByaW50OiBTSEEyNTY6JytmaW5nZXJwcmludCkKICAgICAgICAgICAgaWYgbm90IG5hdGl2ZSBhbmQgZmluZ2VycHJpbnQhPWV4cGVjdGVkOgogICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKCdTdG9jayBob3N0IGtleSBkaWZmZXJzIGZyb20gdGhlIHZlcmlmaWVkIG9yaWdpbmFsIHJvdXRlcicpCiAgICAgICAgICAgIGlmIGlucHV0KCdUcnVzdCB0aGlzIGRpcmVjdGx5IGNvbm5lY3RlZCByb3V0ZXI/IFR5cGUgeWVzOiAnKS5zdHJpcCgpIT0neWVzJzpyYWlzZSBSdW50aW1lRXJyb3IoJ0hvc3Qga2V5IG5vdCBhY2NlcHRlZCcpCiAgICAgICAgICAgIHNzaC5nZXRfaG9zdF9rZXlzKCkuYWRkKGhvc3RuYW1lLGtleS5nZXRfbmFtZSgpLGtleSk7c3NoLnNhdmVfaG9zdF9rZXlzKHN0cihrbm93bikpCiAgICBjbGllbnQuc2V0X21pc3NpbmdfaG9zdF9rZXlfcG9saWN5KEZpcnN0Q29ubmVjdGlvbigpKQogICAgaW5kZXg9d2luZG93c19pbmRleCgpCiAgICBwYXNzd29yZD1nZXRwYXNzLmdldHBhc3MoJ05hdGl2ZSByb290IHBhc3N3b3JkIChzZXQgaXQgaW4gTHVDSSBmaXJzdCk6ICcpIGlmIG5hdGl2ZSBlbHNlIChzdG9ja19wYXNzd29yZCgpIGlmIGluZGV4IGlzIE5vbmUgZWxzZSBOb25lKQogICAgaWYgKG5hdGl2ZSBvciBpbmRleCBpcyBOb25lKSBhbmQgbm90IHBhc3N3b3JkOnJhaXNlIFJ1bnRpbWVFcnJvcignU1NIIHBhc3N3b3JkIGlzIGVtcHR5OyBubyByb3V0ZXIgY29ubmVjdGlvbiBhdHRlbXB0ZWQnKQogICAgc29jaz1zb2NrZXQuc29ja2V0KCk7c29jay5zZXR0aW1lb3V0KDE1KQogICAgaWYgaW5kZXggaXMgbm90IE5vbmU6c29jay5zZXRzb2Nrb3B0KHNvY2tldC5JUFBST1RPX0lQLDMxLHN0cnVjdC5wYWNrKCchSScsaW5kZXgpKQogICAgdHJ5OgogICAgICAgIHNvY2suYmluZCgocGNfaXB2NCwwKSk7c29jay5jb25uZWN0KChyb3V0ZXJfaXB2NCxwb3J0KSkKICAgICAgICBpZiBub3QgbmF0aXZlIGFuZCBpbmRleCBpcyBub3QgTm9uZTpwYXNzd29yZD1zdG9ja19wYXNzd29yZChpbmRleCkKICAgICAgICBjbGllbnQuY29ubmVjdChyb3V0ZXJfaXB2NCxwb3J0PXBvcnQsdXNlcm5hbWU9J3Jvb3QnLHBhc3N3b3JkPXBhc3N3b3JkLHNvY2s9c29jayxhbGxvd19hZ2VudD1GYWxzZSxsb29rX2Zvcl9rZXlzPUZhbHNlLHRpbWVvdXQ9MTUsYmFubmVyX3RpbWVvdXQ9MTUsYXV0aF90aW1lb3V0PTIwKQogICAgICAgIGlmIG5vdCBuYXRpdmU6cmVxdWlyZV9zdG9ja19ob3N0X2tleShjbGllbnQsZXhwZWN0ZWQpCiAgICBleGNlcHQgQmFzZUV4Y2VwdGlvbjpjbGllbnQuY2xvc2UoKTtzb2NrLmNsb3NlKCk7cmFpc2UKICAgIGZpbmFsbHk6cGFzc3dvcmQ9Tm9uZQogICAgcmV0dXJuIGNsaWVudA=='), '<wired-ssh-connection>', 'exec'), controller.__dict__)
original_getpass = getpass.getpass
def required_password(prompt):
    value = original_getpass(prompt)
    if not value:
        raise RuntimeError('SSH password is empty; no router connection attempted')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RuntimeError('Password contains console control characters; type it directly instead of Ctrl+V')
    return value
getpass.getpass = required_password
sys.argv = arguments
runpy.run_path(package, run_name='__main__')
'@

function Grant-TaskUserWorkAccess {
    param([string]$WorkPath, [string]$PackageHash)
    if (-not (Test-Path -LiteralPath $WorkPath)) { return }
    $taskMarker = Join-Path $WorkPath 'installer-sha256.txt'
    if (-not (Test-Path -LiteralPath $taskMarker) -or
        [IO.File]::ReadAllText($taskMarker).Trim() -ne $PackageHash) { throw '工作目录身份不匹配，不能调整备份访问权限。' }
    $taskRows = @(Get-Item -LiteralPath $WorkPath) + @(Get-ChildItem -LiteralPath $WorkPath -Recurse -Force -ErrorAction Stop)
    if (@($taskRows | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw '工作目录含链接，不能调整访问权限。'
    }
    # Python 3.14 may assign an elevated mkdir(0700) to the Administrators owner.
    # Grant only this same human user access, retaining the private directory ACL.
    $taskSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    foreach ($taskRow in $taskRows) {
        $taskAcl = Get-Acl -LiteralPath $taskRow.FullName
        $taskInheritance = if ($taskRow.PSIsContainer) { [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit' } else { [Security.AccessControl.InheritanceFlags]::None }
        $taskAccess = [Security.AccessControl.FileSystemAccessRule]::new($taskSid, [Security.AccessControl.FileSystemRights]::Modify,
            $taskInheritance, [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow)
        $taskAcl.SetAccessRule($taskAccess)
        Set-Acl -LiteralPath $taskRow.FullName -AclObject $taskAcl
    }
}

function Restore-TaskInterruptedNetwork {
    param([string]$PythonPath, [string]$WorkPath, [string]$LogRoot, [string]$PackagePath, [string]$PackageHash)
    $taskAddresses = @(Get-NetIPAddress -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop |
        Where-Object IPAddress -in @('192.168.2.148','192.168.1.148'))
    $taskRoutes = @(Get-NetRoute -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop |
        Where-Object DestinationPrefix -in @('192.168.2.50/32','192.168.1.1/32'))
    $taskBefore = Join-Path $WorkPath 'network\before.json'
    $taskSource = $null
    if (Test-Path -LiteralPath $taskBefore) {
        $taskCurrent = Get-Content -LiteralPath $taskBefore -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($taskCurrent.restored -ne $true) { $taskSource = $WorkPath }
        elseif ($taskAddresses.Count -or $taskRoutes.Count) { throw '快照记录已恢复，但仍有临时网络配置，需要人工核对。' }
    }
    if (-not $taskSource -and -not $taskAddresses.Count -and -not $taskRoutes.Count) { return }
    if (@(Get-NetUDPEndpoint -ErrorAction Stop | Where-Object LocalPort -eq 39001).Count) {
        throw '进度接收程序仍在运行，不能恢复网络或重复安装。'
    }
    if (@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -match 'stock-ssh-installer\.pyz'
    }).Count) { throw '另一个安装器进程仍在运行，请保留窗口并核对。' }
    $taskAdapter = @(Get-NetAdapter -Name '以太网' -ErrorAction Stop)
    if ($taskAdapter.Count -ne 1 -or -not $taskAdapter[0].HardwareInterface -or
        [int]$taskAdapter[0].NdisPhysicalMedium -ne 14) { throw '恢复对象必须是物理以太网网卡。' }
    $taskIndex = $taskAdapter[0].InterfaceIndex
    if (@($taskAddresses | Where-Object { $_.InterfaceIndex -ne $taskIndex -or $_.PrefixLength -ne 24 }).Count -or
        @($taskRoutes | Where-Object { $_.InterfaceIndex -ne $taskIndex -or $_.NextHop -ne '0.0.0.0' -or $_.RouteMetric -ne 1 }).Count) {
        throw '临时地址或路由与安装器配置不一致，需要人工核对。'
    }
    Remove-TaskStaleProgressRule -PythonPath $PythonPath -WorkPath $WorkPath -LogRoot $LogRoot -InspectOnly
    if (-not $taskSource) {
        $taskSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $taskBin = Join-Path ([IO.Path]::GetPathRoot($WorkPath)) ('$Recycle.Bin\' + $taskSid)
        $taskCandidates = @()
        if (Test-Path -LiteralPath $taskBin) {
            foreach ($taskItem in @(Get-ChildItem -LiteralPath $taskBin -Force -Filter '$I*' -ErrorAction Stop)) {
                $taskBytes = [IO.File]::ReadAllBytes($taskItem.FullName)
                if ($taskBytes.Length -lt 28) { continue }
                $taskVersion = [BitConverter]::ToInt64($taskBytes, 0)
                if ($taskVersion -notin @(1,2)) { continue }
                $taskOffset = if ($taskVersion -eq 2) { 28 } else { 24 }
                $taskOriginal = [Text.Encoding]::Unicode.GetString($taskBytes, $taskOffset, $taskBytes.Length - $taskOffset).TrimEnd([char]0)
                if ($taskOriginal -ne $WorkPath) { continue }
                $taskRecycled = Join-Path $taskBin ('$R' + $taskItem.Name.Substring(2))
                if (Test-Path -LiteralPath (Join-Path $taskRecycled 'network\before.json')) {
                    $taskCandidates += [pscustomobject]@{ Path = $taskRecycled; Deleted = [BitConverter]::ToInt64($taskBytes, 16) }
                }
            }
        }
        $taskNewest = $taskCandidates | Sort-Object Deleted -Descending | Select-Object -First 1
        if (-not $taskNewest) { throw '未找到原网络快照；不能猜测原配置或直接删除临时地址。' }
        $taskSource = $taskNewest.Path
    }
    $taskState = Get-Content -LiteralPath (Join-Path $taskSource 'network\before.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($taskState.format -ne 'mer1200g-ssh-cycle-network-v1' -or $taskState.restored -ne $false -or
        $taskState.mac -ne $taskAdapter[0].MacAddress -or $taskState.adapter_guid -ne [string]$taskAdapter[0].InterfaceGuid -or
        $taskState.python -ne $PythonPath -or $taskState.dhcp -notin @('Enabled','Disabled') -or
        $taskState.automatic_metric -notin @('Enabled','Disabled')) { throw '原快照的网卡、安装器或恢复状态不匹配。' }
    # A deleted run directory can contain evidence of a RAM handover. Never restart it here.
    if (@(Get-ChildItem -LiteralPath (Join-Path $taskSource 'bundle') -Directory -Filter 'run-*' -ErrorAction SilentlyContinue).Count) {
        throw '旧工作目录已有路由器执行记录，请核对记录后再决定下一步。'
    }
    $taskRecovery = Join-Path $LogRoot ('MER1200G-network-recovery-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ'))
    $taskStageCode = @'
import pathlib, shutil, sys, zipfile
package, source, recovery, identity = map(str, sys.argv[1:])
source, recovery = pathlib.Path(source), pathlib.Path(recovery)
assert (source / 'installer-sha256.txt').read_text(encoding='ascii').strip() == identity, 'Snapshot belongs to another installer'
with zipfile.ZipFile(package) as archive:
    script = archive.read('assets/network.ps1')
assert (source / 'network/network.ps1').read_bytes() == script, 'Original network script changed'
assert not source.is_symlink(), 'Source directory is a link'
for item in source.rglob('*'):
    assert not item.is_symlink() and not item.is_junction(), 'Work directory contains a link'
recovery.mkdir(mode=0o700)
shutil.copytree(source, recovery / 'original-work')
network = recovery / 'network'
network.mkdir(mode=0o700)
(network / 'network.ps1').write_bytes(script)
shutil.copyfile(source / 'network/before.json', network / 'before.json')
'@
    & $PythonPath -X utf8 -c $taskStageCode $PackagePath $taskSource $taskRecovery $PackageHash
    if ($LASTEXITCODE -ne 0) { throw '原快照和工作目录备份失败；未改网络。' }
    Write-Host ('已保留原工作目录和网络快照：' + $taskRecovery)
    & (Join-Path $PSHOME 'powershell.exe') -NoProfile -ExecutionPolicy Bypass -File (Join-Path $taskRecovery 'network\network.ps1') -Mode Restore -InterfaceAlias '以太网' -PythonExecutable $PythonPath
    if ($LASTEXITCODE -ne 0) { throw '按原快照恢复失败，请保留目录和报错窗口。' }
    if (@(Get-NetIPAddress -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop | Where-Object IPAddress -in @('192.168.2.148','192.168.1.148')).Count -or
        @(Get-NetRoute -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop | Where-Object DestinationPrefix -in @('192.168.2.50/32','192.168.1.1/32')).Count) {
        throw '恢复后仍有临时网络配置，停止安装。'
    }
    if ($taskSource -eq $WorkPath) {
        Copy-Item -LiteralPath (Join-Path $taskRecovery 'network\before.json') -Destination $taskBefore -ErrorAction Stop
    }
    Write-Host 'NETWORK_RECOVERY_PASS：已按原快照恢复电脑网络，可重新准备。' -ForegroundColor Green
}

function Remove-TaskStaleProgressRule {
    param([string]$PythonPath, [string]$WorkPath, [string]$LogRoot, [switch]$InspectOnly)
    $taskRules = @(Get-NetFirewallRule -Name 'MER1200G-STOCK-SSH-INSTALLER' -ErrorAction SilentlyContinue)
    if ($taskRules.Count -eq 0) { return }
    if ($taskRules.Count -ne 1) { throw '同名进度规则不唯一，需要核对后处理。' }
    $taskRule = $taskRules[0]
    $taskPorts = @($taskRule | Get-NetFirewallPortFilter -ErrorAction Stop)
    $taskAddresses = @($taskRule | Get-NetFirewallAddressFilter -ErrorAction Stop)
    $taskApps = @($taskRule | Get-NetFirewallApplicationFilter -ErrorAction Stop)
    $taskServices = @($taskRule | Get-NetFirewallServiceFilter -ErrorAction Stop)
    $taskInterfaces = @($taskRule | Get-NetFirewallInterfaceFilter -ErrorAction Stop)
    $taskInterfaceTypes = @($taskRule | Get-NetFirewallInterfaceTypeFilter -ErrorAction Stop)
    $taskSecurity = @($taskRule | Get-NetFirewallSecurityFilter -ErrorAction Stop)
    $taskKnown = $taskPorts.Count -eq 1 -and $taskAddresses.Count -eq 1 -and $taskApps.Count -eq 1 -and
        $taskServices.Count -eq 1 -and $taskInterfaces.Count -eq 1 -and $taskInterfaceTypes.Count -eq 1 -and $taskSecurity.Count -eq 1 -and
        $taskRule.DisplayName -eq 'MER1200G SSH installer progress' -and
        [int]$taskRule.Enabled -eq 1 -and [int]$taskRule.Direction -eq 1 -and [int]$taskRule.Action -eq 2 -and
        [int]$taskRule.Profile -eq 0 -and [int]$taskRule.PolicyStoreSourceType -eq 1 -and $taskRule.PolicyStoreSource -eq 'PersistentStore' -and
        [string]::IsNullOrEmpty([string]$taskRule.Group) -and [string]::IsNullOrEmpty([string]$taskRule.Description) -and
        [string]$taskPorts[0].Protocol -in @('UDP','17') -and [string]$taskPorts[0].LocalPort -eq '39001' -and [string]$taskPorts[0].RemotePort -eq 'Any' -and
        @($taskAddresses[0].LocalAddress).Count -eq 1 -and [string]$taskAddresses[0].LocalAddress -eq '192.168.2.148' -and
        @($taskAddresses[0].RemoteAddress).Count -eq 1 -and [string]$taskAddresses[0].RemoteAddress -eq '192.168.2.50' -and
        [IO.Path]::GetFullPath([string]$taskApps[0].Program) -eq [IO.Path]::GetFullPath($PythonPath) -and
        [string]::IsNullOrEmpty([string]$taskApps[0].Package) -and [string]$taskServices[0].Service -eq 'Any' -and
        @($taskInterfaces[0].InterfaceAlias).Count -eq 1 -and [string]$taskInterfaces[0].InterfaceAlias -eq 'Any' -and [int]$taskInterfaceTypes[0].InterfaceType -eq 0 -and
        [int]$taskSecurity[0].Authentication -eq 0 -and [int]$taskSecurity[0].Encryption -eq 0 -and -not $taskSecurity[0].OverrideBlockRules -and
        [string]$taskSecurity[0].LocalUser -eq 'Any' -and [string]$taskSecurity[0].RemoteUser -eq 'Any' -and [string]$taskSecurity[0].RemoteMachine -eq 'Any'
    if (-not $taskKnown) { throw '同名规则与安装器标准配置不一致，需要人工核对。' }
    if ($InspectOnly) {
        Write-Host 'PROGRESS_RULE_SIGNATURE_PASS：旧规则与安装器标准配置一致；仅检查。'
        return
    }
    $taskBefore = Join-Path $WorkPath 'network\before.json'
    if (Test-Path -LiteralPath $taskBefore) {
        $taskPrevious = Get-Content -LiteralPath $taskBefore -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($taskPrevious.restored -ne $true) { throw '本工作目录有未恢复的网络快照，需要先按原快照恢复。' }
    }
    if (@(Get-NetIPAddress -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop | Where-Object IPAddress -in @('192.168.2.148','192.168.1.148')).Count -ne 0) {
        throw '仍存在安装器临时地址，需先核对原网络快照。'
    }
    if (@(Get-NetRoute -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop | Where-Object DestinationPrefix -in @('192.168.2.50/32','192.168.1.1/32')).Count -ne 0) {
        throw '仍存在安装器专用路由，需先核对原网络快照。'
    }
    if (@(Get-NetUDPEndpoint -ErrorAction Stop | Where-Object LocalPort -eq 39001).Count -ne 0) {
        throw 'UDP 39001 仍有进度接收程序运行，请保留当前窗口并核对。'
    }
    $taskReceipt = Join-Path $LogRoot ('MER1200G-firewall-backup-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ') + '.json')
    $taskRecord = [ordered]@{
        name = $taskRule.Name; display_name = $taskRule.DisplayName
        action = [string]$taskRule.Action; direction = [string]$taskRule.Direction; profile = [string]$taskRule.Profile
        protocol = [string]$taskPorts[0].Protocol; local_port = [string]$taskPorts[0].LocalPort; remote_port = [string]$taskPorts[0].RemotePort
        local_address = @($taskAddresses[0].LocalAddress); remote_address = @($taskAddresses[0].RemoteAddress)
        program = [string]$taskApps[0].Program; reason = 'Verified installer residue without temporary addresses, routes, listener, or pending snapshot in this work directory'
    }
    [IO.File]::WriteAllText($taskReceipt, ($taskRecord | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
    $taskRule | Remove-NetFirewallRule -Confirm:$false -ErrorAction Stop
    if (Get-NetFirewallRule -Name 'MER1200G-STOCK-SSH-INSTALLER' -ErrorAction SilentlyContinue) { throw '旧进度规则未成功清理。' }
    Write-Host 'NETWORK_RESIDUE_CLEANED：已备份并清理确认无占用的旧进度规则。' -ForegroundColor Green
}

try {
    if ($env:MER1200G_LAUNCHER_MODE -and -not $taskVerifyOnly) {
        throw '启动参数无效；双击启动，或使用 verify 仅检查本地文件。'
    }
    $taskLauncher = [IO.Path]::GetFullPath($env:MER1200G_LAUNCHER_FILE)
    $taskRoot = Split-Path -Parent $taskLauncher
    $taskApp = Join-Path $taskRoot 'immortalwrt-ramips-mt7620-mercury_mer1200g-v1-stock-ssh-installer.pyz'
    $taskWork = Join-Path $taskRoot 'MER1200G-20261121-212926-work'
    $taskExpectedHash = '2ab4e449616242f3d816fe372f6c2fb3510756ad0701356c134b707d41919472'
    if (-not (Test-Path -LiteralPath $taskApp -PathType Leaf)) {
        throw '请将此启动脚本与该 Release 的 .pyz 安装包放在同一文件夹。'
    }
    $taskHasher = [Security.Cryptography.SHA256]::Create()
    $taskStream = [IO.File]::OpenRead($taskApp)
    try {
        $taskActualHash = [BitConverter]::ToString($taskHasher.ComputeHash($taskStream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $taskStream.Dispose()
        $taskHasher.Dispose()
    }
    if ($taskActualHash -ne $taskExpectedHash) {
        throw '安装包与 2026-11-21 21.29.26 Release 不一致；停止运行。'
    }
    $taskPython = (Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    if ($taskVerifyOnly) {
        & $taskPython -X utf8 -c $taskStockCompatibility $taskApp verify
        if ($LASTEXITCODE -ne 0) { throw '安装包本地校验失败。' }
        Write-Host 'LAUNCHER_VERIFY_PASS：路径和发布文件哈希正确；本地校验完成。' -ForegroundColor Green
        $taskExitCode = 0
    } else {
        $taskPrincipal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
        if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            $taskBootstrap = @'
$env:MER1200G_LAUNCHER_FILE = '__LAUNCHER_PATH__'
$env:MER1200G_LAUNCHER_MODE = ''
$text = Get-Content -LiteralPath $env:MER1200G_LAUNCHER_FILE -Raw -Encoding UTF8
$parts = $text -split '(?m)^# MER1200G_POWERSHELL_BEGIN\r?$', 2
if ($parts.Count -ne 2) { throw 'Launcher body missing' }
& ([scriptblock]::Create($parts[1]))
'@
            $taskBootstrap = $taskBootstrap.Replace('__LAUNCHER_PATH__', $taskLauncher.Replace("'", "''"))
            $taskEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($taskBootstrap))
            $taskParentWindow = $true
            $taskChild = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -Verb RunAs -WindowStyle Normal -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$taskEncoded) -Wait -PassThru
            $taskExitCode = $taskChild.ExitCode
        } else {
            $taskOwnInstall = $true
            Set-Location -LiteralPath $taskRoot
            Write-Host 'MER1200G 首次刷入：2026-11-21 21.29.26 Release' -ForegroundColor Cyan
            Write-Host ('安装记录和原始备份：' + $taskWork)
            $taskDependencyCheck = @'
import sys
try:
    import paramiko
    valid = paramiko.__version__ == '3.5.1'
except Exception:
    valid = False
sys.exit(0 if valid else 1)
'@
            & $taskPython -c $taskDependencyCheck
            if ($LASTEXITCODE -ne 0) {
                Write-Host '安装 SSH 依赖 paramiko==3.5.1，请保持电脑能联网。'
                & $taskPython -m pip install --disable-pip-version-check paramiko==3.5.1
                if ($LASTEXITCODE -ne 0) { throw 'SSH 依赖安装失败；恢复电脑联网后再处理。' }
            }
            Write-Host ''
            Write-Host '准备：原厂地址 192.168.2.50，已开启故障诊断模式。'
            Write-Host '拔掉路由器上联网线，电脑网线直连机身第 5 口。'
            Write-Host '流程：准备网络 -> 备份检查 -> 演练 -> 正式刷入 -> 恢复电脑网络。'
            Write-Host '两次断电重启都必须等窗口出现 READY_FOR_POWER_CYCLE；拔电 5 秒后插回。' -ForegroundColor Yellow
            Write-Host '原厂诊断密码自动按直连设备 LAN MAC 计算，不保存；指纹仍需确认。'
            Write-Host '新系统启动后在 192.168.1.1 设置 root 密码，再按提示手动输入。'
            [void](Read-Host '网线和诊断模式准备好后，按 Enter 开始')
            Restore-TaskInterruptedNetwork -PythonPath $taskPython -WorkPath $taskWork -LogRoot $taskRoot -PackagePath $taskApp -PackageHash $taskExpectedHash
            Remove-TaskStaleProgressRule -PythonPath $taskPython -WorkPath $taskWork -LogRoot $taskRoot
            & $taskPython -X utf8 -c $taskStockCompatibility $taskApp install --workdir $taskWork --direct-lan
            if ($LASTEXITCODE -ne 0) { throw '安装器已停止。保持路由器当前供电状态和本窗口，不要重新双击启动。' }
            $taskSucceeded = $true
            $taskExitCode = 0
            Write-Host '安装完成，SSH 验收通过，电脑网络已恢复。' -ForegroundColor Green
        }
    }
} catch {
    Write-Host ('STOP：' + $_.Exception.Message) -ForegroundColor Red
    $taskExitCode = 1
} finally {
    if ($taskOwnInstall) {
        try { Grant-TaskUserWorkAccess -WorkPath $taskWork -PackageHash $taskExpectedHash }
        catch { Write-Host ('备份目录仍需管理员访问：' + $_.Exception.Message) -ForegroundColor Yellow }
    }
    if (-not $taskVerifyOnly -and -not $taskParentWindow) {
        if ($taskSucceeded) {
            [void](Read-Host '按 Enter 关闭窗口')
        } else {
            [void](Read-Host '先保留窗口并将错误输出发给助手；处理完成后按 Enter 关闭')
        }
    }
}
exit $taskExitCode
