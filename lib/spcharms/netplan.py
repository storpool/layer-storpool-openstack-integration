"""
A StorPool Juju charm helper module: parse the netplan configuration.
"""


import netplan


def get_related(ifaces, exclude=["99-storpool.yaml"]):
    """
    Parse the current netplan configuration, by default excluding
    the modifications made by the charm.
    """
    parser = netplan.Parser()
    data = parser.parse(exclude=exclude)
    return data.get_all_interfaces(ifaces)
