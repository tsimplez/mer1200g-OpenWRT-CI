#!/bin/bash
# SPDX-License-Identifier: MIT
# Run from the ImmortalWrt checkout; keep this device path isolated from other targets.
set -euo pipefail

CI_ROOT=${GITHUB_WORKSPACE:?GITHUB_WORKSPACE must identify the CI checkout}
PATCH_DIR="$CI_ROOT/Patches/MER1200G"
REPORT_DIR="$CI_ROOT/build-reports"
test -f include/toplevel.mk
mkdir -p "$REPORT_DIR"
json_field() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' "$1" "$2"
}

case "${1:-}" in
  source)
    PATCH_FILE="$PATCH_DIR/$(json_field "$PATCH_DIR/source.json" device_patch)"
    EXPECTED=$(json_field "$PATCH_DIR/source.json" device_patch_sha256)
    printf '%s  %s\n' "$EXPECTED" "$PATCH_FILE" | sha256sum -c -
    if git apply --check --whitespace=nowarn "$PATCH_FILE" 2> "$REPORT_DIR/mer1200g-apply-check.log"; then
      # Nested kernel patches contain whitespace as part of their patch context.
      git apply --whitespace=nowarn "$PATCH_FILE"
      PATCH_STATE=applied
    elif git apply --reverse --check --whitespace=nowarn "$PATCH_FILE" 2>> "$REPORT_DIR/mer1200g-apply-check.log"; then
      PATCH_STATE=already-present
    else
      cat "$REPORT_DIR/mer1200g-apply-check.log" >&2
      echo 'MER1200G source support is neither applicable nor present verbatim; review the upstream change.' >&2
      exit 1
    fi
    {
      printf 'source_commit=%s\n' "$(git rev-parse HEAD)"
      printf 'patch_base=%s\n' "$(json_field "$PATCH_DIR/source.json" source_base_commit)"
      printf 'patch_sha256=%s\npatch_state=%s\n' "$EXPECTED" "$PATCH_STATE"
    } | tee "$REPORT_DIR/mer1200g-source.txt"
    cp "$PATCH_DIR/source.json" "$REPORT_DIR/mer1200g-source.json"
    ;;
  theme)
    THEME_REPO=$(json_field "$CI_ROOT/Config/MER1200G-theme.json" repository)
    THEME_COMMIT=$(json_field "$CI_ROOT/Config/MER1200G-theme.json" commit)
    [[ "$THEME_COMMIT" =~ ^[0-9a-f]{40}$ ]]
    THEME_DIR=package/luci-theme-vantage
    if [ ! -e "$THEME_DIR" ]; then
      git init "$THEME_DIR"
      git -C "$THEME_DIR" remote add origin "$THEME_REPO"
      git -C "$THEME_DIR" fetch --depth=1 origin "$THEME_COMMIT"
      git -C "$THEME_DIR" checkout --detach FETCH_HEAD
    fi
    test "$(git -C "$THEME_DIR" rev-parse HEAD)" = "$THEME_COMMIT"
    git -C "$THEME_DIR" diff --quiet HEAD --
    test -f "$THEME_DIR/luci-theme-vantage/Makefile"
    cp "$CI_ROOT/Config/MER1200G-theme.json" "$REPORT_DIR/mer1200g-theme.json"
    ;;
  settings)
    cat "$CI_ROOT/Config/MER1200G.txt" > .config
    if [ -f "$CI_ROOT/Config/PRIVATE.txt" ]; then
      cat "$CI_ROOT/Config/PRIVATE.txt" >> .config
    fi
    if [ -n "${WRT_PACKAGE:-}" ]; then
      printf '%b\n' "$WRT_PACKAGE" >> .config
    fi
    ;;
  verify-config)
    for symbol in \
      TARGET_ramips TARGET_ramips_mt7620 TARGET_ramips_mt7620_DEVICE_mercury_mer1200g-v1 \
      TARGET_ROOTFS_INITRAMFS TARGET_ROOTFS_SQUASHFS LINUX_6_18 LUCI_LANG_zh_Hans \
      PACKAGE_luci PACKAGE_luci-theme-vantage PACKAGE_luci-i18n-vantage-theme-zh-cn PACKAGE_luci-i18n-base-zh-cn \
      PACKAGE_default-settings-chn PACKAGE_dropbear PACKAGE_firewall4 PACKAGE_dnsmasq-full \
      PACKAGE_ppp-mod-pppoe PACKAGE_kmod-mt76x2 PACKAGE_kmod-rt2800-soc PACKAGE_kmod-switch-rtl8367b; do
      grep -Fxq "CONFIG_$symbol=y" .config || {
        echo "Required MER1200G option missing after defconfig: CONFIG_$symbol=y" >&2
        exit 1
      }
    done
    test "$(grep -Ec '^CONFIG_TARGET_.*_DEVICE_.*=y$' .config)" -eq 1
    echo 'MER1200G required features and single-device selection verified.'
    cp .config "$REPORT_DIR/mer1200g.config"
    ;;
  *) echo 'Usage: prepare-mer1200g.sh {source|theme|settings|verify-config}' >&2; exit 2 ;;
esac
