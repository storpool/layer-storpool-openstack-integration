"""
A Juju charm layer that installs the StorPool OpenStack integration into
the current node and, if configured, its LXD containers.
"""
from __future__ import print_function

from charmhelpers.core import hookenv

from spcharms import status as spstatus
from spcharms import utils as sputils

from spcharms.run import storpool_common as run_common


def rdebug(s):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix="openstack-integration")


openstack_components = ["cinder", "nova"]


def enable_and_start():
    """
    Run the StorPool OpenStack integration on the current node and,
    if configured, its LXD containers.
    """
    if not hookenv.config()["storpool_openstack_install"]:
        rdebug("skipping the installation into containers")
        return

    # to do: check for the nova-compute and cinder-volume services

    # to do: set up the groups

    spstatus.npset("maintenance", "")


def run():
    rdebug("Run, common, run!")
    run_common.run()
    rdebug("Returning to the StorPool OpenStack integration setup")
    enable_and_start()


def stop():
    """
    Clean up on deinstallation.
    """
    rdebug("storpool-osi.stop invoked")

    rdebug("letting storpool-common know")
    run_common.stop()
