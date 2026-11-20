/* SPDX-License-Identifier: MIT
 * Device bindings occupy one read-only ELF section. Keep policy.c in a separate
 * translation unit and build without LTO so checks load the bound bytes rather
 * than propagating template literals into instructions.
 */
#ifndef MER_INSTALL_POLICY_H
#define MER_INSTALL_POLICY_H
/* stage_policy.h is also force-included by the build. Feature selection must
 * precede the first libc header just as it does in the original source files. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif
#ifndef _FILE_OFFSET_BITS
#define _FILE_OFFSET_BITS 64
#endif
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define MER_POLICY_MAGIC "MERPOLICY-V1"
#define MER_POLICY_VERSION 1u
#define MER_POLICY_BYTES 748u

struct mer_install_policy_data {
 char magic[16];
 uint32_t version;
 uint32_t policy_bytes;
 uint32_t preflight_bytes;
 uint32_t snapshot_helper_bytes;
 char image_sha[65];
 char backup_sha[65];
 char stock_sha[65];
 char boot_sha[65];
 char device_info_sha[65];
 char firmware_info_sha[65];
 char tddp_sha[65];
 char art_sha[65];
 char preflight_nonce[33];
 char write_nonce[33];
 char preflight_sha[65];
 char snapshot_helper_sha[65];
};

_Static_assert(sizeof(uint32_t)==4,"Policy requires uint32_t");
_Static_assert(offsetof(struct mer_install_policy_data,version)==16,"Policy version offset");
_Static_assert(offsetof(struct mer_install_policy_data,policy_bytes)==20,"Policy length offset");
_Static_assert(offsetof(struct mer_install_policy_data,preflight_bytes)==24,"Preflight length offset");
_Static_assert(offsetof(struct mer_install_policy_data,snapshot_helper_bytes)==28,"Snapshot length offset");
_Static_assert(offsetof(struct mer_install_policy_data,image_sha)==32,"Image offset");
_Static_assert(offsetof(struct mer_install_policy_data,backup_sha)==97,"Backup offset");
_Static_assert(offsetof(struct mer_install_policy_data,stock_sha)==162,"Stock offset");
_Static_assert(offsetof(struct mer_install_policy_data,boot_sha)==227,"Boot offset");
_Static_assert(offsetof(struct mer_install_policy_data,device_info_sha)==292,"Device-info offset");
_Static_assert(offsetof(struct mer_install_policy_data,firmware_info_sha)==357,"Firmware-info offset");
_Static_assert(offsetof(struct mer_install_policy_data,tddp_sha)==422,"TDDP offset");
_Static_assert(offsetof(struct mer_install_policy_data,art_sha)==487,"ART offset");
_Static_assert(offsetof(struct mer_install_policy_data,preflight_nonce)==552,"Preflight nonce offset");
_Static_assert(offsetof(struct mer_install_policy_data,write_nonce)==585,"Write nonce offset");
_Static_assert(offsetof(struct mer_install_policy_data,preflight_sha)==618,"Preflight hash offset");
_Static_assert(offsetof(struct mer_install_policy_data,snapshot_helper_sha)==683,"Snapshot hash offset");
_Static_assert(sizeof(struct mer_install_policy_data)==MER_POLICY_BYTES,"Policy has no padding");

extern const struct mer_install_policy_data mer_install_policy;

#define MER_BACKUP_SHA (mer_install_policy.backup_sha)
#define MER_IMAGE_SHA (mer_install_policy.image_sha)
#define MER_STOCK_SHA (mer_install_policy.stock_sha)
#define MER_BOOT_SHA (mer_install_policy.boot_sha)
#define MER_DEVICE_INFO_SHA (mer_install_policy.device_info_sha)
#define MER_FIRMWARE_INFO_SHA (mer_install_policy.firmware_info_sha)
#define MER_TDDP_SHA (mer_install_policy.tddp_sha)
#define MER_ART_SHA (mer_install_policy.art_sha)
#define MER_PREFLIGHT_NONCE (mer_install_policy.preflight_nonce)
#define MER_WRITE_NONCE (mer_install_policy.write_nonce)
#define MER_PREFLIGHT_SHA (mer_install_policy.preflight_sha)
#define MER_PREFLIGHT_BYTES (mer_install_policy.preflight_bytes)
#define MER_SNAPSHOT_HELPER_SHA (mer_install_policy.snapshot_helper_sha)
#define MER_SNAPSHOT_HELPER_BYTES (mer_install_policy.snapshot_helper_bytes)
#define MER_BUNDLE_IMAGE_SHA MER_IMAGE_SHA
#define MER_SNAPSHOT_DESIRED MER_IMAGE_SHA
#define MER_SNAPSHOT_BOOT MER_BOOT_SHA
#define MER_SNAPSHOT_ALLOC 30408704u

static inline int mer_policy_hex(const char *value,size_t length){
 for(size_t i=0;i<length;i++)
  if(!((value[i]>='0' && value[i]<='9') || (value[i]>='a' && value[i]<='f')))return -1;
 return value[length]? -1:0;
}
static inline int mer_install_policy_validate(int require_helpers){
 const struct mer_install_policy_data *p=&mer_install_policy;
 static const char expected_magic[16]=MER_POLICY_MAGIC;
 if(memcmp(p->magic,expected_magic,sizeof(p->magic)) || p->version!=MER_POLICY_VERSION ||
    p->policy_bytes!=MER_POLICY_BYTES || (require_helpers!=0 && require_helpers!=1))return -1;
 const char *hashes[]={p->image_sha,p->backup_sha,p->stock_sha,p->boot_sha,
                       p->device_info_sha,p->firmware_info_sha,p->tddp_sha,p->art_sha};
 for(size_t i=0;i<sizeof(hashes)/sizeof(hashes[0]);i++)if(mer_policy_hex(hashes[i],64))return -1;
 if(mer_policy_hex(p->preflight_nonce,32) || mer_policy_hex(p->write_nonce,32))return -1;
 /* These fields are unused in the two upstream helpers. Leaving them unbound
  * there avoids including a helper's own SHA256 in the helper it identifies. */
 if(require_helpers && (!p->preflight_bytes || p->preflight_bytes>0xcf0000u ||
    !p->snapshot_helper_bytes || p->snapshot_helper_bytes>0xcf0000u ||
    mer_policy_hex(p->preflight_sha,64) || mer_policy_hex(p->snapshot_helper_sha,64)))return -1;
 return 0;
}
#endif
