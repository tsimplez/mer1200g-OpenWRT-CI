# MER1200G 设备支持来源

`0001-native-support.patch` 导出自本地已实测的 VIKINGYFY/immortalwrt 修改，基准为 `2bb59802ceeb8bcba408a7b6694f0c4669e24eab`（2026-11-12）。`source.json` 记录补丁 SHA256 与八个原始文件的 SHA256；不含 `.gitignore`、私有 MAC、密码、备份或 CI 机器路径。原文件的 SPDX/许可头保留。

| 源文件 | 专业用途 | 通俗说明 |
| --- | --- | --- |
| `target/linux/ramips/dts/mt7620a_mercury_mer1200g-v1.dts` | 描述内存、RTL8367S交换机、双频EEPROM/MAC、保护区与可动态分割的firmware分区 | 告诉系统这台路由器有哪些硬件、接在哪里、哪些闪存不能动 |
| `target/linux/ramips/dts/mt7620a_mercury_mer1200g-v1-initramfs.dts` | RAM测试专用设备树，禁止firmware解析并使全部MTD只读 | 试运行新系统时给闪存加只读锁 |
| `target/linux/ramips/image/mt7620.mk` | 注册设备profile，声明驱动包、内核入口与镜像流水线 | 让编译菜单出现MER1200G，并自动生成它能用的镜像 |
| `target/linux/ramips/mt7620/base-files/etc/board.d/02_network` | 设置五口WAN/LAN的VLAN/PVID及派生WAN MAC | 定义哪个网口接外网，哪些给家里设备用 |
| `scripts/mer1200g-image.py` | 生成原厂U-Boot可读的multi-uImage/LZMA封装，计算CRC并检查边界 | 把系统打包成路由器启动程序认识的格式，并检查大小 |
| `333-MIPS-ralink-use-appended-DT-for-MER1200G.patch` | MER1200G专用早期入口保护，使用附加DTB并跳过不兼容的固件argv | 让新内核正确接过原厂启动程序的接力棒 |
| `334-mt7620-avoid-direct-jal-in-timing-entropy.patch` | MT7620定时熵路径三处混合调用改为间接调用，保留随机数算法 | 绕开实测导致启动卡死的一种跳转方式，不关闭随机数功能 |
| `761-net-dsa-add-ralink-metadata-tagger.patch` | 刷新原有DSA补丁上下文和协议编号冲突 | 修好上游补丁之间的冲突，让当前源码能编译 |

`prepare-mer1200g.sh source` 先校验补丁哈希，再执行 `git apply --check`。源码已逐字包含这些修改时，必须通过严格的反向检查才能跳过；其他情况停止构建。未来内核/上游变化使补丁失配时，应在实际源码中重审并重新导出，不能删除检查或忽略应用失败。

主题独立锁在 `Config/MER1200G-theme.json`，不混进板级补丁。defconfig后同时要求Linux 6.18系列，避免切到其它内核时漏用早期启动补丁。上游仓库本身尚未收录本地支持，因此直接在本CI改SOURCE仓库/BRANCH即可构建的前提，是目标分支仍兼容这份补丁，或已经逐字包含它；跨内核系列需要重新移植与实测。

## 固件发布与取回

打包时保留原生固件文件名，只发布一份根据实际附件重新生成的 `SHA256SUMS`；不复制上游的 `sha256sums`，重复打包时也会清理旧校验文件。解压固件 Artifact 后，可在文件所在目录运行 `sha256sum -c SHA256SUMS` 校验。

完整编译通过镜像检查后，先将发布目录保存为 `firmware-MER1200G-<源码作者>-<运行次数>` Artifact，保留 7 天，再串行上传 GitHub Release 附件。发布 Action 固定到 v3.0.4 的提交；发布步骤失败时，可从该次 Actions 运行页面的 Artifacts 下载已编译固件及配套报告，无需为取回这些文件重新编译。仅验证配置的 TEST 模式不生成固件 Artifact。
