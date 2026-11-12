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
  find "$IMAGE_DIR" -maxdepth 1 -type f -exec cp -t upload/ -- {} +
  cp "$REPORT_DIR/mer1200g-image-sizes.json" "$REPORT_DIR/mer1200g-firmware-metadata.json" upload/
  # Recalculate against the files actually published; keep native firmware names intact.
  (cd upload && find . -maxdepth 1 -type f ! -name sha256sums ! -name SHA256SUMS -printf '%f\0' | sort -z | xargs -0 sha256sum > SHA256SUMS)
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
    printf '`squashfs-sysupgrade.bin` 用于已完成原生分区迁移的 MER1200G v1；原厂和旧 V2 不能直接刷此包。\n\n'
    printf '`initramfs-kernel.RAM-ONLY.bin` 仅供 U-Boot 从 RAM 启动，不能写入闪存。\n\n'
    printf '默认 LAN 地址 192.168.1.1。保留配置升级时沿用现有密码、网络和主题设置。\n\n'
    printf '本次已做镜像格式、容量、必需包和升级元数据检查；云构建不代表已完成实机启动/升级验证。\n\n'
    printf '完整配置、manifest、buildinfo、容量报告和 SHA256SUMS 一起提供。\n'
  fi
} > "$REPORT_DIR/mer1200g-release.md"
