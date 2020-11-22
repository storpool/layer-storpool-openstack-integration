"""
A Juju layer for installing and configuring the base StorPool packages.
"""
from __future__ import print_function

import subprocess

from spcharms import error as sperror
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


def run():
    rdebug("Run, repo, run!")
    run_repo.run()
    rdebug("Returning to the storpool-config setup")

    try:
        data = (
            subprocess.check_output(
                ["storpool_confshow", "-ne", "SP_OURID"], shell=False
            )
            .decode("UTF-8")
            .splitlines()
        )
    except (IOError, subprocess.CalledProcessError):
        raise sperror.StorPoolMissingComponentsError(["storpool_confshow"])

    if len(data) != 1:
        raise sperror.StorPoolMissingComponentsError(["SP_OURID"])

    try:
        our_id = int(data[0])
    except ValueError:
        raise sperror.StorPoolMissingComponentsError(["valid SP_OURID"])

    rdebug("Got our StorPool ID {our_id}".format(our_id=our_id))


def stop():
    """
    Clean up, remove configuration files, uninstall packages... or not.
    """
    rdebug("storpool-config.stop invoked")

    rdebug("let the storpool-repo layer know that we are shutting down")
    run_repo.stop()
