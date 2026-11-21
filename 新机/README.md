# 原厂 到 ImmortalWrt

密码 5049939d

下载
immortalwrt-ramips-mt7620-mercury_mer1200g-v1-stock-ssh-installer.pyz

将 `开始刷入.cmd` 与同一目录的 `immortalwrt-ramips-mt7620-mercury_mer1200g-v1-stock-ssh-installer.pyz` 一起保留，双击 CMD，允许管理员运行。

1. 原厂 LAN 地址设为 `192.168.2.50`，开启“故障诊断模式”。拔掉上联网线，电脑直连机身第 5 口。
2. 原厂诊断 SSH 密码自动按直连设备的 LAN MAC 计算，不需要输入；按提示确认本机指纹。程序自动准备网络、备份、检查、演练、刷写和验收。
3. 两次都只在出现 `READY_FOR_POWER_CYCLE` 后拔电 5 秒再插回。第一次原厂启动后重新开启诊断模式；第二次在 `192.168.1.1` 设置 root 密码并按提示完成 SSH 验收。
4. 等待 `INSTALL_PASS`、`INSTALL_COMPLETE`，再关闭窗口。

报错时保留供电、窗口和工作目录。不能删除记录或重复激活 RAM 安装器。仅网络准备阶段中断时，CMD 会核对原快照并恢复；删除到回收站的工作目录可核对并备份后恢复。存在 RAM 执行记录或接收程序时停止自动重试。

本 CMD 固定以下 Release，包含原厂 BusyBox 缺少 `stat` 时的只读设备节点检查适配，不修改固件或跳过保护检查：

https://github.com/tsimplez/mer1200g-OpenWRT-CI/releases/tag/MER1200G-VIKINGYFY-owrt-26.11.21-21.29.26

原始 `.pyz` SHA256：`2ab4e449616242f3d816fe372f6c2fb3510756ad0701356c134b707d41919472`。

CMD 已适配认证失败时的 SSH 关闭顺序，避免附带出现 Windows socket 10038。原厂登录先建立绑定有线网卡的 TCP 连接，让 Windows 解析当前设备的 ARP，再读取唯一的 `192.168.2.50` 邻居 MAC 并在内存计算密码；网络重新准备后无需已有 ARP 缓存。SSH 指纹仍需确认，不再通过隐藏输入读取原厂密码。邻居记录缺失、歧义或不匹配时停止。新系统 root 密码仍手动输入，不保存；空密码或控制字符会停止登录。本次失败发生在登录准备阶段，没有 RAM 激活或刷写记录，可关闭旧报错窗口后重新双击同一 CMD；保留工作目录和路由器供电。

在本目录运行 `cmd /c 开始刷入.cmd verify` 只检查本地文件。程序不会保存密码；生成的工作目录含本机完整原厂备份，应保留在本地。已有 ImmortalWrt 时不运行首次安装；回原厂后再次安装可继续使用同一 CMD 和安装包。
