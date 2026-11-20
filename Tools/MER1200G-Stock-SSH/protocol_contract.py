# SPDX-License-Identifier: MIT
"""Strict reliable-status wire contract; legacy bundles are not compatible."""

STATUS_PROTOCOL = 'mer1-stopwait-sha256-v1'
ACK_WAIT_MS = 5000
FINAL_GRACE_SECONDS = 10


def require_protocol(manifest):
    if manifest.get('status_protocol') != STATUS_PROTOCOL:
        raise ValueError('Bundle status protocol differs; rebuild with installer-reliable')
