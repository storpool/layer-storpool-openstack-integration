"""
A Juju charm layer that installs and starts the StorPool block (client)
service from the StorPool Ubuntu package repository.
"""
from __future__ import print_function

from spcharms import status as spstatus
from spcharms import utils as sputils

from spcharms.run import storpool_beacon as run_beacon


def rdebug(s):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix="block")


def run():
    """
    Invoke install_package() and enable_and_start() as needed.
    """
    rdebug("Run, beacon, run!")
    run_beacon.run()
    rdebug("Returning to the storpool_block setup")
    sputils.check_systemd_service("storpool_block")
    spstatus.npset("maintenance", "")


def stop():
    """
    Remove the installed packages and stop the service.
    """
    rdebug("storpool-block.stop invoked")

    rdebug("let storpool-beacon know")
    run_beacon.stop()
