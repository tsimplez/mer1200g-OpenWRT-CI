#!/bin/bash
# SPDX-License-Identifier: MIT
set -euo pipefail

CI_ROOT=${GITHUB_WORKSPACE:?GITHUB_WORKSPACE must identify the CI checkout}
REPORT_DIR="$CI_ROOT/build-reports"
mkdir -p upload "$REPORT_DIR"
json_field() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' "$1" "$2"
}
cp .config upload/MER1200G.config
cp "$REPORT_DIR"/mer1200g-source.{txt,json} "$REPORT_DIR/mer1200g-theme.json" upload/

if [ "${WRT_TEST:-false}" != true ]; then
  IMAGE_DIR=bin/targets/ramips/mt7620
  python3 "$CI_ROOT/.github/scripts/verify-mer1200g-images.py" "$IMAGE_DIR" --output "$REPORT_DIR/mer1200g-image-sizes.json"
  NORMAL_IMAGE="$IMAGE_DIR/immortalwrt-ramips-mt7620-mercury_mer1200g-v1-squashfs-sysupgrade.bin"
  staging_dir/host/bin/fwtool -i "$REPORT_DIR/mer1200g-firmware-metadata.json" "$NORMAL_IMAGE"
  python3 - "$REPORT_DIR/mer1200g-firmware-metadata.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    metadata = json.load(f)
if "mercury,mer1200g-v1" not in metadata.get("supported_devices", []):
    raise SystemExit("MER1200G support missing from sysupgrade metadata")
PY
  find "$IMAGE_DIR" -maxdepth 1 -type f ! -iname sha256sums -exec cp -t upload/ -- {} +
  cp "$REPORT_DIR/mer1200g-image-sizes.json" "$REPORT_DIR/mer1200g-firmware-metadata.json" upload/
  # One desktop package contains this build's firmware and SSH installer.
  # Use the same MIPS little-endian musl toolchain that built the firmware;
  # silently selecting a host compiler or an ambiguous cached toolchain is unsafe.
  shopt -s nullglob
  INSTALLER_COMPILERS=(staging_dir/toolchain*/bin/mipsel-*musl*gcc)
  shopt -u nullglob
  if [ "${#INSTALLER_COMPILERS[@]}" -ne 1 ] || [ ! -x "${INSTALLER_COMPILERS[0]}" ]; then
    echo 'Expected exactly one executable MIPS little-endian musl compiler for the stock SSH installer.' >&2
    exit 1
  fi
  INSTALLER_PACKAGE=upload/immortalwrt-ramips-mt7620-mercury_mer1200g-v1-stock-ssh-installer.pyz
  STAGING_DIR="$PWD/staging_dir" python3 "$CI_ROOT/Tools/MER1200G-Stock-SSH/build_installer.py" \
    --sysupgrade "$NORMAL_IMAGE" \
    --cc "$PWD/${INSTALLER_COMPILERS[0]}" \
    --output "$INSTALLER_PACKAGE"
  if [ ! -s "$INSTALLER_PACKAGE" ]; then
    echo 'Stock SSH installer package was not produced.' >&2
    exit 1
  fi
  # Test policy binding under MIPS and the production core's memory-only
  # failure matrix before releasing the new installer.
  STAGING_DIR="$PWD/staging_dir" python3 "$CI_ROOT/Tools/MER1200G-Stock-SSH/verify_installer.py" \
    --package "$INSTALLER_PACKAGE" \
    --cc "$PWD/${INSTALLER_COMPILERS[0]}" \
    --output "$REPORT_DIR/mer1200g-stock-ssh-offline.json"
  python3 - "$REPORT_DIR/mer1200g-stock-ssh-offline.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    report = json.load(f)
if not isinstance(report, dict) or report.get("passed") is not True or \
        report.get("hardware_tested") is not False or report.get("router_accessed") is not False:
    raise SystemExit("Stock SSH offline report must confirm success without router access or hardware testing")
PY
  MER1200G_SYSUPGRADE="$PWD/$NORMAL_IMAGE" python3 -m unittest discover \
    -s "$CI_ROOT/Tools/MER1200G-Stock-SSH/tests" -p 'test_*.py'
  cp "$REPORT_DIR/mer1200g-stock-ssh-offline.json" upload/
  # Publish one checksum list, including when packaging is rerun in the same directory.
  find upload -maxdepth 1 -type f -iname sha256sums -delete
  (cd upload && find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\0' | sort -z | xargs -0 sha256sum > SHA256SUMS)
fi

{
  printf '# MERCURY MER1200G v1\n\n'
  printf '源码：%s\n\n分支：%s\n\n提交：%s\n\n' "$WRT_REPO" "$WRT_BRANCH" "$WRT_HASH"
  printf '设备支持补丁：`%s`\n\n' "$(json_field "$CI_ROOT/Patches/MER1200G/source.json" device_patch_sha256)"
  printf 'Vantage：`%s`，提交 `%s`。中文 LuCI 和主题翻译保留。\n\n' \
    "$(json_field "$CI_ROOT/Config/MER1200G-theme.json" version)" "$(json_field "$CI_ROOT/Config/MER1200G-theme.json" commit)"
  if [ "${WRT_TEST:-false}" = true ]; then
    printf '本次仅生成配置，没有编译固件。\n'
  else
    printf '`stock-ssh-installer.pyz` 是电脑端单文件首次安装包，内含本次固件和 SSH 工具，适用于核验通过的原厂 MER1200G Ver1.1。电脑安装 Python 和包内说明要求的依赖后运行；程序通过 SSH 保存新机备份并完成绑定、演练和安装，无需用户制作 bundle。它不用于原厂网页上传升级。\n\n'
    printf '`squashfs-sysupgrade.bin` 用于已完成原生分区迁移的 MER1200G v1；原厂和旧 V2 不能直接刷此包。\n\n'
    printf '`initramfs-kernel.RAM-ONLY.bin` 仅供 U-Boot 从 RAM 启动，不能写入闪存。\n\n'
    printf '默认 LAN 地址 192.168.1.1。保留配置升级时沿用现有密码、网络和主题设置。\n\n'
    printf '本次已做镜像格式、容量、升级元数据、MIPS policy 与模拟闪存故障检查；首刷包限匹配已记录原厂版本的 Ver1.1，新机仍需实际演练、冷启动和安装验收，云构建不代表这些检查已经完成。\n\n'
    printf '完整配置、manifest、buildinfo、容量报告和 SHA256SUMS 一起提供。\n'
  fi
} > "$REPORT_DIR/mer1200g-release.md"
