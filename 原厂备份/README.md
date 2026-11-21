# ImmortalWrt 回原厂

适用于本机 MER1200G 的固件内核均为 `6.18.60`。当前管理地址为 `192.168.1.1`。

1. 拔掉上联网线，电脑直连 LAN。在电脑 PowerShell 上传镜像和最新预检脚本，然后登录：

   ```shell
   # 密钥问题
   ssh-keygen -R 192.168.1.1
   ```

   ```powershell
   scp -O "E:\Project\Github\OpenWRT-CI\原厂备份\mer1200g-stock-firmware.bin" "E:\Project\Github\OpenWRT-CI\原厂备份\stock-preflight.sh" root@192.168.1.1:/tmp/
   ```
   ```shell
   ssh root@192.168.1.1
   ```

2. 在路由器 SSH 中执行这一行；预检通过后立即回刷：

   ```sh
   sh /tmp/stock-preflight.sh && /sbin/sysupgrade -F -n --no-provisioning /tmp/mer1200g-stock-firmware.bin
   ```

   必须出现 `STOCK_PREFLIGHT_PASS` 和 `policy=v3`。出现 `STOP` 时不要跳过检查，保留输出。

3. SSH 断开后保持供电，等待约 5 分钟自动重启。电脑有线保持 DHCP；必要时拔插网线重新获取地址，再打开 `http://192.168.2.50`
   。如访问不了，查看电脑新获得的默认网关。

回刷覆盖 ImmortalWrt 及其配置，保留原厂配置、bootloader 和 ART。原厂 LAN 地址来自保留配置，本机预期为 `192.168.2.50`。

`mer1200g-stock-firmware.bin` 是 13,565,952 字节的原厂回刷镜像。`full-flash.bin` 是 16 MiB 整片备份，保留供 SPI 编程器恢复，不能交给
sysupgrade。每次回刷都重新上传最新脚本；历史预检脚本保留在 `历史预检`。
