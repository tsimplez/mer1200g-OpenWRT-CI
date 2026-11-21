# MER1200G 原厂 SSH 首次安装包

本目录是可提交到 Git 的通用生成工具。CI 编译 ImmortalWrt 时，同时生成一个
`immortalwrt-ramips-mt7620-mercury_mer1200g-v1-stock-ssh-installer.pyz`。
固件和安装程序一起放在这个文件中；在电脑上通过 Python 运行，程序使用 SSH 操作原厂路由器。
每台新机的完整备份、SSH 身份及安装包绑定在本地自动生成，不需要把另一台机器的 `bundle` 拿来使用。

首版适用范围是 MERCURY MER1200G **机身 Ver1.1、原厂网页型号版本 v1.0**，匹配已验证原厂固件窗口 SHA256，
并使用原厂 Linux 3.10、128 MiB RAM、16 MiB SPI NOR 和对应原厂 10 分区布局。
已验证的原厂版本是 `1.0.2 Build 20190815 Rel.80403`，固件窗口 SHA256 为
`f4a1e7740eb453ec0f685e6b1803f86a701d5dfba3c04e1e1b3d4e3b3d74f6c4`。
该哈希只包含公用原厂 kernel/rootfs 窗口，不包含每台机器的 MAC、ART 或其它保护区。
其它型号、硬件版本、分区或不在包内白名单的原厂固件版本停止安装；未知原厂版本需要先做只读兼容适配。
2026-11-22 已在本机完成 2026-11-21 21.29.26 Release 的原厂备份、RAM 演练、207 块刷写读回和新系统 SSH 启动验收。
该原始 Release 通过配套 CMD 适配了原厂 BusyBox 缺少 `stat` 的情况；当前采集器已改为直接校验 `ls -ln` 的设备节点号。
这次实测记录仅适用于该固件和设备；其它 CI 产物仍需实机验证。
本入口用于仍运行原厂系统的新机。已安装 ImmortalWrt 的机器使用后续升级流程，不重复运行首次安装。

## 编译并下载

在 GitHub Actions 运行 **MER1200G**，使用 `TEST=false`。Release 中下载本次的
`*-stock-ssh-installer.pyz`，并核对同一 Release 的 `SHA256SUMS`。
`.pyz` 是包含固件的电脑端安装程序，下载这一个文件即可使用。
在电脑上执行 `python <安装包>.pyz ...`；它不上传到原厂网页，也不在路由器中用 `sh` 执行。
后续普通升级继续使用 `squashfs-sysupgrade.bin`。
CI 无需接收新机 MAC、密码或完整备份；新机专属数据只在实际操作的电脑上生成。

电脑需要 Python 3.10 或更新版本，以及安装器使用的依赖：

```powershell
python -m pip install paramiko==3.5.1
```

## 新机准备

1. 在原厂网页确认型号和硬件版本，将 LAN 管理地址改为 `192.168.2.50`。
2. 开启“故障诊断模式”，在原厂网页记下这台新机的 **LAN MAC**。诊断 SSH 端口为 `33400`。
3. 拔掉路由器的上联网线，电脑网线直连机身第 **5** 口。
4. 打开管理员 PowerShell，使用同一个安装包和同一个工作目录完成各步。

## 一条命令完成安装流程

下面以安装包放在 `D:\MER1200G` 为例；`$app` 指向实际下载的文件。每台新机选择独立的 `$work`。

```powershell
$app = "D:\MER1200G\immortalwrt-ramips-mt7620-mercury_mer1200g-v1-stock-ssh-installer.pyz"
$work = "D:\MER1200G\新机-01"
```

先本地计算诊断 SSH 密码，把下面的 `<新机LAN MAC>` 替换为原厂网页显示的 LAN MAC：

```powershell
python -X utf8 $app password --mac "<新机LAN MAC>"
```

输出是 8 位诊断密码，可用于旧版安装包的 `Stock root SSH password` 提示。
该计算在本地完成，不连接路由器；公式是去掉 MAC 分隔符、转大写、计算 MD5，取前 8 位小写十六进制字符。
当前 Windows 安装流程先通过绑定有线网卡的 TCP 连接解析 ARP，再读取唯一的原厂 LAN 邻居 MAC，自动在内存中计算诊断密码，保留 SSH 指纹确认。邻居缺失、歧义或网卡不匹配时停止，不猜测 MAC。新系统 root 密码仍交互输入，终端不显示字符，密码不写入文件；手动配置的非 Windows 流程也保留原厂密码输入。

管理员 PowerShell 执行下面这一条安装命令：

```powershell
python -X utf8 $app install --workdir $work --direct-lan
```

`install` 依次准备电脑网络、备份及检查新机、演练、正式刷入、恢复电脑网络。
接受直接连接的新机 SSH 指纹后，后续步骤会继续核对这台机器的身份。
流程中有两次人工断电重启：

1. 演练到 `READY_FOR_POWER_CYCLE` 后拔电，等 5 秒再插回。原厂启动后必要时重新开启诊断模式，按窗口提示按 Enter，等待 `REHEARSAL_PASS`。当前 Windows 流程自动计算诊断 SSH 密码；旧包仍按提示输入。
2. 正式刷入到新的 `READY_FOR_POWER_CYCLE` 后拔电，等 5 秒再插回。新系统启动后打开 `http://192.168.1.1`，在 LuCI 设置 root 密码，再按窗口提示完成 SSH 验收。

保持供电和窗口，只按明确的 READY 提示进行断电。最后 `INSTALL_PASS` 表示写入读回、保护区和新固件启动核验通过，`INSTALL_COMPLETE` 表示电脑网络也已恢复。

任何一步报错或中断，程序停止后续步骤、保留工作目录和电脑网络状态，不自动恢复网络、不重新激活安装器。
接管到 RAM 后报错、HOLD、缺少 READY 或 PASS 时，保持供电并保留输出；按窗口提示只重试认证检查。

## 逐步操作或继续检查

也可以使用各个独立子命令，按顺序逐项检查：

```powershell
python -X utf8 $app prepare --workdir $work --direct-lan
python -X utf8 $app check --workdir $work
python -X utf8 $app rehearse --workdir $work
python -X utf8 $app flash --workdir $work
python -X utf8 $app restore --workdir $work
```

每项通过后才手动执行下一项，演练和正式安装的重启要求与上面的单命令流程一致。
独立 `check` 的第一次采集会保存两次完整闪存读取得到的原厂基线，再自动生成新机 bundle。
两次读取的原厂固件和保护区必须一致、boot ID 必须保持不变；日志和配置区可以发生运行中的变化。
原厂固件窗口还必须匹配安装包内已验证版本的 SHA256 白名单。遇到未知版本，只保留完整备份和 FAILED 记录，不生成安装许可。
原厂 BusyBox 1.22.1 没有 `stat` 命令；采集器使用 `ls -ln` 读取 `/dev/mtd9` 的字符设备号，
仍要求该节点为 `90:18`、不是符号链接，并独立校验 sysfs 中的 NOR 类型、容量及擦写几何。
首次只读采集失败时，可重新运行 `check`，采集器会建立新的时间戳目录，保留失败记录和已保存的备份。
已有 bundle 时，`check` 只再次核对当前原厂状态，不重新生成备份或机器身份。

不指定动作或使用 `verify` 时，只校验本地安装包，不连接路由器或修改电脑网络。
网卡名称不是“以太网”时，使用 `--interface-alias "实际有线网卡名称"`。

## 收尾和保留文件

单命令安装成功后已经恢复电脑网络。逐步操作时，恢复网络使用本次同一个工作目录：

```powershell
python -X utf8 $app restore --workdir $work
```

默认工作目录是安装包同目录下的 `<安装包文件名去掉扩展名>-work`；建议显式指定每台新机独立的 `--workdir`。
工作目录绑定同一个安装包，下一台新机或另一份固件选择新目录。

```text
新机-01/
  captures/<时间戳>/full-flash.bin       新机原始完整备份
  captures/<时间戳>/stock-bootstrap.json 采集核验记录
  bundle/                              自动生成的本机安装包及安装记录
  network/before.json                  本次电脑网络恢复快照
```

下载时只需一个 `.pyz` 文件。每台机器独立保留原始 `full-flash.bin` 和安装结果；
工作目录包含本机专属数据，不作为公共 CI 产物或上传到 Git。尚未恢复的电脑网络快照留在原工作目录。

## 离线检查

新机备份采集器的测试只使用模拟 SSH，不连接或刷写路由器：

```powershell
python -m unittest discover -s Tools/MER1200G-Stock-SSH/tests -v
```
