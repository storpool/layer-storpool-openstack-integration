"""
A Juju charm layer that checks for the `storpool_beacon` service.
"""
from __future__ import print_function

from spcharms import status as spstatus
from spcharms import utils as sputils

from spcharms.run import storpool_openstack_integration as run_osi


def rdebug(s):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix="beacon")


def run():
    rdebug("Run, OpenStack integration, run!")
    run_osi.run()
    rdebug("Returning to the storpool-beacon setup")
    sputils.check_systemd_service("storpool_beacon")
    spstatus.npset("maintenance", "")


def stop():
    """
    Clean up, disable the service, uninstall the packages.
    """
    rdebug("storpool-beacon.stop invoked")

    rdebug("letting storpool-openstack-integration know")
    run_osi.stop()
