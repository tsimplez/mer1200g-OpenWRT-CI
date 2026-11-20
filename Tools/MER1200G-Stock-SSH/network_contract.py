# SPDX-License-Identifier: MIT
"""Fixed endpoint contract shared by this local controller and bundle builder."""

NETWORK = {
    'router_ipv4': '192.168.2.50',
    'pc_ipv4': '192.168.2.148',
    'ssh_port': 33400,
    'udp_port': 39001,
    'native_router_ipv4': '192.168.1.1',
    'native_pc_ipv4': '192.168.1.148',
    'native_ssh_port': 22,
}


def require_network(manifest):
    if manifest.get('network') != NETWORK:
        raise ValueError('Bundle network contract differs; use the newly built SSH-cycle bundle')


def ssh_endpoint(native=False):
    prefix = 'native_' if native else ''
    return (NETWORK[prefix + 'router_ipv4'], NETWORK[prefix + 'pc_ipv4'],
            NETWORK[prefix + 'ssh_port'])
