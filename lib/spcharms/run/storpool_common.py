"""
A Juju charm layer that installs the base StorPool packages.
"""
from __future__ import print_function

from spcharms import utils as sputils

from spcharms.run import storpool_config as run_config


def rdebug(s, cond=None):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix="common", cond=cond)


def run():
    rdebug("Run, config, run!")
    run_config.run()
    rdebug("Returning to the storpool-common setup")


def stop():
    """
    Clean up, remove the config files, uninstall the packages.
    """
    rdebug("storpool-common.stop invoked")

    rdebug("letting storpool-config know")
    run_config.stop()
