"""
A Juju layer for installing and configuring the base StorPool packages.
"""
from __future__ import print_function

from spcharms import config as spconfig
from spcharms import status as spstatus
from spcharms import utils as sputils

from spcharms.run import storpool_repo_add as run_repo


def rdebug(s, cond=None):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix="config", cond=cond)


def config_changed():
    """
    Check if the configuration is complete or has been changed.
    """
    rdebug("config-changed happened")


def read_config():
    """
    Read the StorPool configuration file.
    """
    rdebug("about to read the /etc/storpool.conf file")
    spstatus.npset("maintenance", "parsing the /etc/storpool.conf file")

    # Remove any states that say we have accomplished anything...
    spconfig.m()
    spconfig.unset_our_id()
    spconfig.drop_cache()

    cfg = spconfig.get_dict()
    oid = cfg["SP_OURID"]
    spconfig.set_our_id(oid)
    rdebug(
        "got {len} keys in the StorPool config, our id is {oid}".format(
            len=len(cfg), oid=oid
        )
    )

    spstatus.npset("maintenance", "")


def run():
    rdebug("Run, repo, run!")
    run_repo.run()
    rdebug("Returning to the storpool-config setup")
    read_config()


def stop():
    """
    Clean up, remove configuration files, uninstall packages... or not.
    """
    rdebug("storpool-config.stop invoked")

    rdebug("let the storpool-repo layer know that we are shutting down")
    run_repo.stop()
