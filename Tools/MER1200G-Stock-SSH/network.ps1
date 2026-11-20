param(
    [ValidateSet('Inspect','Prepare','Restore')][string]$Mode = 'Inspect',
    [string]$InterfaceAlias = '以太网',
    [string]$PythonExecutable = '',
    [switch]$DirectLan
)

$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskStatePath = Join-Path $taskRoot 'before.json'
$taskRuleName = 'MER1200G-STOCK-SSH-INSTALLER'
$taskPcIps = @('192.168.2.148','192.168.1.148')
$taskRouterRoutes = @('192.168.2.50/32','192.168.1.1/32')

function Require-Administrator {
    $taskPrincipal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw '请在管理员 PowerShell 运行 Prepare / Restore。'
    }
}

function Save-State($State) {
    [IO.File]::WriteAllText($taskStatePath, ($State | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
}

function Read-Adapter {
    $taskFound = @(Get-NetAdapter -Name $InterfaceAlias)
    if ($taskFound.Count -ne 1 -or -not $taskFound[0].HardwareInterface -or
        [int]$taskFound[0].NdisPhysicalMedium -ne 14) {
        throw '指定接口必须是唯一的物理以太网网卡。请用 -InterfaceAlias 指定有线接口名称。'
    }
    return $taskFound[0]
}

function Read-TaskIPv4 {
    # Query the provider first, then filter locally: an empty adapter is valid
    # during DHCP disable/restart. Provider or permission errors still stop.
    Get-NetIPAddress -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop |
        Where-Object { $_.InterfaceIndex -eq $taskIndex }
}

function Read-TaskRoutes {
    Get-NetRoute -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop |
        Where-Object { $_.InterfaceIndex -eq $taskIndex }
}

function Remove-TaskIPv4($Rows) {
    foreach ($taskRow in $Rows) {
        Remove-NetIPAddress -InterfaceIndex $taskIndex -IPAddress $taskRow.IPAddress -AddressFamily IPv4 -PolicyStore ActiveStore -Confirm:$false
    }
}

function Remove-TaskRoutes($Rows) {
    foreach ($taskRow in $Rows) {
        Remove-NetRoute -InterfaceIndex $taskIndex -DestinationPrefix $taskRow.DestinationPrefix -NextHop $taskRow.NextHop -AddressFamily IPv4 -PolicyStore ActiveStore -Confirm:$false
    }
}

function Wait-TaskDhcp([string]$Expected) {
    if ($Expected -notin @('Disabled','Enabled')) { throw '快照中的 DHCP 状态无效。' }
    $taskExpectedValue = if ($Expected -eq 'Enabled') { 1 } else { 0 }
    $taskDhcpDeadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $taskDhcpRows = @(Get-NetIPInterface -InterfaceIndex $taskIndex -AddressFamily IPv4 -PolicyStore ActiveStore)
        $taskDhcpMatches = $taskDhcpRows.Count -eq 1 -and
            $taskDhcpRows[0].InterfaceIndex -eq $taskIndex -and
            [int]$taskDhcpRows[0].AddressFamily -eq 2 -and
            $null -ne $taskDhcpRows[0].Dhcp -and
            [int]$taskDhcpRows[0].Dhcp -eq $taskExpectedValue
        if (-not $taskDhcpMatches) { Start-Sleep -Milliseconds 250 }
    } while (-not $taskDhcpMatches -and [DateTime]::UtcNow -lt $taskDhcpDeadline)
    if (-not $taskDhcpMatches) { throw ('有线 DHCP 在 15 秒内未变为 ' + $Expected + '。') }
}

$taskAdapter = Read-Adapter
$taskIndex = $taskAdapter.InterfaceIndex
if ($Mode -eq 'Inspect') {
    $taskAdapter | Format-List Name,InterfaceIndex,MacAddress,Status | Out-String | Write-Output
    Read-TaskIPv4 |
        Select-Object IPAddress,PrefixLength,PrefixOrigin | Format-Table -AutoSize | Out-String | Write-Output
    Read-TaskRoutes |
        Where-Object { $_.DestinationPrefix -in $taskRouterRoutes } |
        Select-Object DestinationPrefix,NextHop,InterfaceIndex | Format-Table -AutoSize | Out-String | Write-Output
    Write-Host 'Inspect 只读：未改网络，也未连接路由器。'
    exit 0
}

Require-Administrator
if ($Mode -eq 'Prepare') {
    if (-not $DirectLan) { throw '先拔掉 MER 的 WAN/上联网线，电脑直连第5口，再添加 -DirectLan 运行。' }
    if (Test-Path -LiteralPath $taskStatePath) {
        $taskExisting = Get-Content -LiteralPath $taskStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $taskExisting.restored) { throw '已有未恢复的网络快照，请先运行 -Mode Restore。' }
        $taskArchive = Join-Path $taskRoot ('before-restored-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ') + '.json')
        Move-Item -LiteralPath $taskStatePath -Destination $taskArchive
    }
    $taskPythonCommand = if ([string]::IsNullOrWhiteSpace($PythonExecutable)) { 'python' } else { $PythonExecutable }
    $taskPython = (& $taskPythonCommand -c "import sys,paramiko; assert paramiko.__version__ == '3.5.1'; print(sys.executable)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $taskPython)) { throw '需要 Python 和 paramiko==3.5.1。' }
    if (Get-NetFirewallRule -Name $taskRuleName -ErrorAction SilentlyContinue) { throw '同名临时防火墙规则已存在，请先核对。' }
    if (Read-TaskRoutes |
        Where-Object { $_.DestinationPrefix -in $taskRouterRoutes }) {
        throw '有线网卡已有同目标的专用路由，请先核对，避免覆盖。'
    }
    $taskIpInterface = Get-NetIPInterface -InterfaceIndex $taskIndex -AddressFamily IPv4 -PolicyStore ActiveStore
    $taskEee = Get-NetAdapterAdvancedProperty -Name $taskAdapter.Name -RegistryKeyword '*EEE' -ErrorAction SilentlyContinue
    $taskDnsRegistry = Get-ItemProperty -LiteralPath ('HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\' + $taskAdapter.InterfaceGuid)
    $taskState = [ordered]@{
        format = 'mer1200g-ssh-cycle-network-v1'
        adapter_guid = [string]$taskAdapter.InterfaceGuid
        mac = $taskAdapter.MacAddress
        dhcp = [string]$taskIpInterface.Dhcp
        automatic_metric = [string]$taskIpInterface.AutomaticMetric
        metric = $taskIpInterface.InterfaceMetric
        ipv4 = @(Read-TaskIPv4 |
            Select-Object IPAddress,PrefixLength,PrefixOrigin,SkipAsSource)
        default_routes = @(Read-TaskRoutes |
            Where-Object { $_.DestinationPrefix -eq '0.0.0.0/0' } |
            Select-Object DestinationPrefix,NextHop,RouteMetric)
        static_dns = [string]$taskDnsRegistry.NameServer
        dns_servers = @((Get-DnsClientServerAddress -InterfaceIndex $taskIndex -AddressFamily IPv4).ServerAddresses)
        eee = if ($taskEee) { @($taskEee.RegistryValue) } else { $null }
        python = $taskPython
        prepared = $false
        restored = $false
    }
    Save-State $taskState
    $taskStage = 'EEE'
    try {
        if ($taskEee -and (@($taskEee.RegistryValue) -join ',') -ne '0') {
            Set-NetAdapterAdvancedProperty -Name $taskAdapter.Name -RegistryKeyword '*EEE' -RegistryValue @('0') -NoRestart
            Restart-NetAdapter -Name $taskAdapter.Name -Confirm:$false
        }
        $taskStage = '关闭有线 DHCP'
        Set-NetIPInterface -InterfaceIndex $taskIndex -AddressFamily IPv4 -Dhcp Disabled -AutomaticMetric Disabled -InterfaceMetric 500 -PolicyStore ActiveStore
        Wait-TaskDhcp 'Disabled'
        $taskStage = '清理当前有线地址与路由'
        Remove-TaskRoutes @(Read-TaskRoutes |
            Where-Object { $_.DestinationPrefix -eq '0.0.0.0/0' -or $_.DestinationPrefix -in $taskRouterRoutes })
        Remove-TaskIPv4 @(Read-TaskIPv4 |
            Where-Object { $_.IPAddress -notlike '169.254.*' })
        $taskStage = '设置临时有线地址'
        foreach ($taskIp in $taskPcIps) {
            New-NetIPAddress -InterfaceIndex $taskIndex -IPAddress $taskIp -PrefixLength 24 -SkipAsSource $false -PolicyStore ActiveStore | Out-Null
        }
        $taskStage = '设置直连路由'
        foreach ($taskRoute in $taskRouterRoutes) {
            New-NetRoute -InterfaceIndex $taskIndex -DestinationPrefix $taskRoute -NextHop '0.0.0.0' -RouteMetric 1 -PolicyStore ActiveStore | Out-Null
        }
        $taskStage = '设置进度防火墙规则'
        New-NetFirewallRule -Name $taskRuleName -DisplayName 'MER1200G SSH installer progress' -Direction Inbound -Action Allow -Profile Any -Protocol UDP -LocalAddress '192.168.2.148' -LocalPort 39001 -RemoteAddress '192.168.2.50' -Program $taskPython | Out-Null
        $taskStage = '验证有线地址与路由'
        $taskAddressDeadline = [DateTime]::UtcNow.AddSeconds(15)
        do {
            $taskNow = @(Read-TaskIPv4 |
                Where-Object { $_.IPAddress -in $taskPcIps })
            if ($taskNow | Where-Object { $_.AddressState -eq 'Duplicate' }) { throw '有线任务地址冲突，请运行 Restore 后检查连接。' }
            $taskReady = @($taskNow | Where-Object { $_.AddressState -eq 'Preferred' }).Count -eq 2
            if (-not $taskReady) { Start-Sleep -Milliseconds 250 }
        } while (-not $taskReady -and [DateTime]::UtcNow -lt $taskAddressDeadline)
        if (-not $taskReady) { throw '有线任务地址尚未就绪；请检查网线和地址冲突。' }
        foreach ($taskRoute in $taskRouterRoutes) {
            if (-not (Read-TaskRoutes | Where-Object { $_.DestinationPrefix -eq $taskRoute })) { throw ('缺少直连路由 ' + $taskRoute) }
        }
        $taskState.prepared = $true
        Save-State $taskState
        Write-Output 'NETWORK_READY：有线设置为 192.168.2.148 和 192.168.1.148；已保存原网络和 EEE 设置。'
    } catch {
        Write-Host ('准备失败 [' + $taskStage + ']：' + $_.Exception.Message + '。快照已保留；运行 -Mode Restore 恢复。') -ForegroundColor Red
        exit 1
    }
} else {
    $taskState = Get-Content -LiteralPath $taskStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($taskState.format -ne 'mer1200g-ssh-cycle-network-v1' -or $taskState.mac -ne $taskAdapter.MacAddress -or
        $taskState.adapter_guid -ne [string]$taskAdapter.InterfaceGuid) { throw '快照与网卡身份不一致。' }
    if ($taskState.restored) { Write-Output '网络已恢复。'; exit 0 }
    Get-NetFirewallRule -Name $taskRuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Remove-TaskRoutes @(Read-TaskRoutes |
        Where-Object { $_.DestinationPrefix -in $taskRouterRoutes })
    Remove-TaskIPv4 @(Read-TaskIPv4 |
        Where-Object { $_.IPAddress -in $taskPcIps })
    if ($taskState.eee) {
        Set-NetAdapterAdvancedProperty -Name $taskAdapter.Name -RegistryKeyword '*EEE' -RegistryValue @($taskState.eee) -NoRestart
        Restart-NetAdapter -Name $taskAdapter.Name -Confirm:$false
    }
    Set-NetIPInterface -InterfaceIndex $taskIndex -AddressFamily IPv4 -Dhcp $taskState.dhcp -AutomaticMetric $taskState.automatic_metric -InterfaceMetric $taskState.metric -PolicyStore ActiveStore
    Wait-TaskDhcp $taskState.dhcp
    if ($taskState.dhcp -eq 'Disabled') {
        foreach ($taskAddress in $taskState.ipv4) {
            if ($taskAddress.IPAddress -notlike '169.254.*' -and -not (Read-TaskIPv4 | Where-Object { $_.IPAddress -eq $taskAddress.IPAddress })) {
                New-NetIPAddress -InterfaceIndex $taskIndex -IPAddress $taskAddress.IPAddress -PrefixLength $taskAddress.PrefixLength -SkipAsSource $taskAddress.SkipAsSource -PolicyStore ActiveStore | Out-Null
            }
        }
        foreach ($taskRoute in $taskState.default_routes) {
            if (-not (Read-TaskRoutes | Where-Object { $_.DestinationPrefix -eq '0.0.0.0/0' -and $_.NextHop -eq $taskRoute.NextHop })) {
                New-NetRoute -InterfaceIndex $taskIndex -DestinationPrefix '0.0.0.0/0' -NextHop $taskRoute.NextHop -RouteMetric $taskRoute.RouteMetric -PolicyStore ActiveStore | Out-Null
            }
        }
    }
    $taskState.restored = $true
    Save-State $taskState
    Write-Output 'NETWORK_RESTORED：临时地址/路由/规则已删除，原网络和 EEE 设置已恢复。DHCP 地址可能需要拔插网线后重新获取。'
}
