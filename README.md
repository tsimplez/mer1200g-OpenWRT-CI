# 高质量<免费>交流群

[IPQ技术讨论群](https://qm.qq.com/q/v7nMhzB4oU)

# 高质量<付费>中转站

[Krill-Code](https://www.krill-code.com/register?invite=959NHQCZGT)

# 本地编译器

https://github.com/VIKINGYFY/OWRT-Tools.git

# 自用修改版插件

https://github.com/VIKINGYFY/packages.git

# OpenWRT-CI

官方版：

https://github.com/immortalwrt/immortalwrt.git

自用版：

https://github.com/VIKINGYFY/immortalwrt.git

# U-BOOT

高通版-沉心：

https://github.com/chenxin527/uboot-qsdk12.5-build.git

高通版-小猪：

https://github.com/1980490718/u-boot-2016.git

联发科-全新版：

https://github.com/VIKINGYFY/UBOOT-CI/releases

联发科-官方版：

https://drive.wrt.moe/uboot/mediatek

# 固件简要说明

固件每天早上5点自动编译。

固件信息里的时间为编译开始的时间，方便核对上游源码提交时间。

MEDIATEK系列、QUALCOMMAX系列、ROCKCHIP系列、X86系列。

# 目录简要说明

workflows——自定义CI配置

Scripts——自定义脚本

Config——自定义配置

## MERCURY MER1200G v1

新增 **Actions → MER1200G → Run workflow**，默认源码 `VIKINGYFY/immortalwrt`、分支 `owrt`。本CI会应用保存的设备支持补丁，不要求先有一个已经收录板级改动的公开源码fork；也可在运行时修改SOURCE/BRANCH。源码与补丁不兼容时构建停止，不能忽略错误继续刷写。

MER1200G使用单独的 `Config/MER1200G.txt`：保留已实测的平台默认功能、SSH、中文LuCI、双频、基本路由，增加 `anothaDev/luci-theme-vantage` 及其中文翻译。Vantage是外观，LuCI中文包是翻译，两者都保留。主题版本/提交锁定在 `Config/MER1200G-theme.json`，可选Vantage仪表盘没有默认加入。

该设备不合并面向大容量设备的 `GENERAL.txt`，不运行通用第三方软件大合集或默认IP/无线密码修改。默认LAN地址192.168.1.1，无线沿用源码默认值；需要添加软件可填写PACKAGE，镜像超出可用闪存会停止。PRIVATE.txt仍可作为本地自定义扩展，必需功能和单设备选择会在defconfig后复核。其它平台继续使用原流程。

编译结果从对应Release下载，保留原始镜像名，并附完整配置、manifest、buildinfo、镜像容量报告、源码/主题来源、升级元数据和 `SHA256SUMS`。TEST勾选时只展开配置，不编译固件。该入口为手动触发，不增加每日自动编译；已有Auto-Clean的清理策略保持原样，需要长期保存的固件请另存。

- `stock-ssh-installer.pyz`：电脑端单文件 SSH 首刷包，包含本次固件和安装器。支持匹配已记录原厂版本的 MER1200G Ver1.1，自动保存新机完整备份、绑定新机身份、演练并刷入，无需手工制作 `bundle`。流程见 [SSH 首刷说明](Tools/MER1200G-Stock-SSH/README.md)。新流程已加入离线核验，仍需新机实机验收。
- `squashfs-sysupgrade.bin`：供**已完成原生分区迁移的MER1200G v1**后续升级使用。原厂及旧V2不能直接使用；本地首次迁移不是普通sysupgrade。
- `initramfs-kernel.RAM-ONLY.bin`：仅用于U-Boot从内存启动，不能写入闪存。
- CI通过仅证明编译、必需包、封装、容量和元数据检查通过。实际启动、无线客户端流量、首次迁移及后续升级需实机确认；LED/Reset GPIO尚未实现。

各板级文件的专业/通俗用途及来源见 [Patches/MER1200G/README.md](Patches/MER1200G/README.md)。

| CI文件 | 专业用途 | 通俗说明 |
| --- | --- | --- |
| `.github/workflows/MER1200G.yml` | 手动参数入口，复用WRT-CORE | 给MER1200G增加一个编译按钮 |
| `.github/workflows/WRT-CORE.yml` | 仅对MER1200G分流准备、配置与发布步骤 | 让这个小容量机型走自己的设置，其它机型照旧 |
| `Config/MER1200G.txt` | 单设备、功能与主题选择 | 这台路由器要装的软件清单 |
| `Config/MER1200G-theme.json` | 主题仓库、版本、提交锁 | 明确这次用哪一版Vantage，避免主题悄悄变化 |
| `Patches/MER1200G/0001-native-support.patch`、`source.json` | 板级移植及来源哈希 | 把本地验证过的设备支持带进云编译 |
| `.github/scripts/prepare-mer1200g.sh` | 应用/识别补丁、固定主题、生成及断言配置 | 编译前安装适配材料并检查机型和必需功能选对了 |
| `.github/scripts/verify-mer1200g-images.py` | 验证uImage/LZMA/CRC、rootfs和overlay边界、安装包清单 | 检查生成的包格式对、放得下、功能没丢 |
| `.github/scripts/package-mer1200g.sh` | 提取并验证升级元数据，保留产物与生成发布说明/哈希 | 把固件和核对资料一起整理好，标清哪个包能升级 |

## Star History

<a href="https://www.star-history.com/?repos=vikingyfy%2Fopenwrt-ci&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=vikingyfy/openwrt-ci&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=vikingyfy/openwrt-ci&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=vikingyfy/openwrt-ci&type=date&legend=top-left" />
 </picture>
</a>
