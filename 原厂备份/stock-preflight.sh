#!/bin/sh
# Only checks. This script never invokes a flash write, reboot, or service stop.
# Policy v3: pin the two verified CI firmware prefixes and device identity.
set -eu
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
IMAGE=/tmp/mer1200g-stock-firmware.bin

stop() { echo "STOP: $*" >&2; exit 1; }
hash_is() {
    local actual
    actual="$(sha256sum "$1")" || stop "Cannot hash $1"
    [ "${actual%% *}" = "$2" ] || stop "SHA256 differs: $1"
}
part_is() {
    local index="$1" label="$2" offset="$3" size="$4" digest="$5" writable="$6"
    local base="/sys/class/mtd/$index" flags
    [ "$(cat "$base/name")" = "$label" ] || stop "Wrong label: $index"
    [ "$(cat "$base/type")" = nor ] || stop "Not NOR: $index"
    [ "$(cat "$base/offset")" -eq "$offset" ] || stop "Wrong offset: $index"
    [ "$(cat "$base/size")" -eq "$size" ] || stop "Wrong size: $index"
    [ "$(cat "$base/erasesize")" -eq 65536 ] || stop "Wrong erase size: $index"
    flags="$(cat "$base/flags")"
    [ "$((flags & 1024))" -eq "$writable" ] || stop "Unexpected write flag: $index"
    [ -c "/dev/$index" ] || stop "Missing character device: $index"
    [ "$digest" = - ] || hash_is "/dev/$index" "$digest"
}

[ "$(id -u)" -eq 0 ] || stop "Run as root"
[ "$(cat /tmp/sysinfo/board_name)" = mercury,mer1200g-v1 ] || stop "Wrong board"
[ "$(uname -r)" = 6.18.60 ] || stop "Unexpected running kernel"
[ "$(awk 'END {print NR}' /proc/mtd)" -eq 13 ] || stop "Unexpected MTD table"
[ -f "$IMAGE" ] || stop "Upload $IMAGE first"
[ "$(wc -c < "$IMAGE")" -eq 13565952 ] || stop "Wrong image length"
hash_is "$IMAGE" f4a1e7740eb453ec0f685e6b1803f86a701d5dfba3c04e1e1b3d4e3b3d74f6c4

part_is mtd1 firmware 262144 13565952 - 1024
part_is mtd0 bootloader 0 262144 fe0f9115e0e4320a0f328f1ef26f5e7460ec5c8819f2a3afaa271e88f87b5a20 0
part_is mtd5 device-info 13828096 65536 32bcf7a2ccb7704e81667db8c502a24a216bee84e37f18e05766e6fe8b0e0c96 0
part_is mtd6 firmware-info 13893632 65536 7f44396c01ab163e69ec23ed9c876e3b74dc4269d3f5bf796cb394c7d41d4cc0 0
part_is mtd7 tddp 13959168 65536 6d330616fe53bbeec29f5c416abd640c2fb3eec6f0227cd293c2b7a1697d208e 0
# These regions are outside the firmware write window. Stock may update them
# between installations; retain their geometry/read-only checks, not old hashes.
part_is mtd8 log 14024704 131072 - 0
part_is mtd9 reserved 14155776 458752 - 0
part_is mtd10 rootfs-data-stock 14614528 2097152 - 0
part_is mtd11 art 16711680 65536 b89e0946c03fff50c2d479cceef486910fda55a9ca9ae54b3d39b743c236e815 0

# mtd1 includes writable overlay data. Accept only these two known immutable
# kernel/SquashFS prefixes. Both builds use the reviewed upgrade programs below.
immutable="$(head -c 9734420 /dev/mtd1 | sha256sum)" || stop "Cannot hash immutable firmware"
if [ "${immutable%% *}" = 5e650c9ca963a62601aff7670962c0469a7a62124fe4cddf49becb7e3c142a21 ]; then
    firmware="2026-11-16 r0-1f21e82"
else
    immutable="$(head -c 9752256 /dev/mtd1 | sha256sum)" || stop "Cannot hash immutable firmware"
    [ "${immutable%% *}" = adbb2fadecbbb94af420b1fac9033b4f33e844dab1c2b9139168e9d83aaca8df ] || stop "Immutable kernel/SquashFS differs: /dev/mtd1 (no verified CI match)"
    firmware="2026-11-21 21.29.26 r0-b650d6e"
fi
echo "INFO: verified firmware=$firmware"
for index in mtd8 mtd9 mtd10; do
    current="$(sha256sum "/dev/$index")" || stop "Cannot read retained region: $index"
    echo "INFO: retained $index SHA256=${current%% *} (mutable; recorded, not pinned)"
done

# Require the exact stock upgrade scripts reviewed for this installed version.
hash_is /sbin/sysupgrade 8f860fbcaefa6d48f81c03ea0b10a909048f724cea9098a3c9eb08fc6def01b8
hash_is /lib/upgrade/platform.sh b0347a7430b065e836442448497adffdeb180f5d65da0b9e5e31d77c3e5225e7
hash_is /lib/upgrade/stage2 c494d3cc230b30da3f5b44f6d5d97f2e05d5a4abb87259111375df69fb2c668c
hash_is /lib/upgrade/do_stage2 b849b405446a5e6b1467d67bdd712e3ade9d215c78cf2bf80264914e21dfeed3
hash_is /lib/upgrade/common.sh fee08a6dcea757850f9071425eaa3959568be58baade4101a8e0dc1dfa967177
hash_is /lib/upgrade/fwtool.sh c8a01b50c628bf53a72dd29afabc9e0e0a1e656ca836fc4002034b96efecfcce
hash_is /usr/libexec/validate_firmware_image 344d0f57b3af9ee13bb1fb4e64eca931d431b3c5157076d693d72a585fc46d43
[ -x /sbin/mtd ] && [ -x /sbin/upgraded ] || stop "Upgrade binaries missing"
[ "$(head -c 4 /sbin/mtd | hexdump -v -e '1/1 "%02x"')" = 7f454c46 ] || stop "mtd is not an ELF binary"
available="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
[ "${available:-0}" -ge 24576 ] || stop "Less than 24 MiB memory available"

# -T stops before services are stopped or flash is written. -F is expected
# because the exact original vendor image has no OpenWrt image metadata.
/sbin/sysupgrade -T -F -n --no-provisioning "$IMAGE" || stop "sysupgrade dry check failed"
echo "STOCK_PREFLIGHT_PASS (checks only; flash has NOT been written; policy=v3)"
