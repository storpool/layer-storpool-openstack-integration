"""
A Juju charm layer that removes the obsolete StorPool MAAS package
repository files from the node's APT configuration.
"""

from __future__ import print_function

import pathlib
import subprocess

from spcharms import utils as sputils

DEFAULT_APT_SOURCES_DIR = pathlib.Path("/etc/apt/sources.list.d")
OBSOLETE_APT_SOURCES_FILES = ("storpool-maas.list", "storpool-maas.sources")
DEFAULT_KEYRING_DIR = pathlib.Path("/usr/share/keyrings")
OBSOLETE_KEYRING_FILES = ("storpool-maas-keyring.gpg",)


def rdebug(s, cond=None):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix="repo-add", cond=cond)


def run():
    """ Set up the StorPool repository if all the configuration is present. """
    rdebug("And now we are at the bottom of the well...")

    # Sources files: run `apt-get update` afterwards.
    rdebug("- checking for obsolete APT source files")
    found = []
    for path in (
        DEFAULT_APT_SOURCES_DIR / name for name in OBSOLETE_APT_SOURCES_FILES
    ):
        if path.exists():
            rdebug("  - removing {path}".format(path=path))
            path.unlink()
            found.append(path)
    if found:
        rdebug("APT sources removed, running apt-get update (errors ignored)")
        subprocess.call(["apt-get", "-q", "-y", "update"], shell=False)

    # Keyring files: no `apt-get update` needed.
    rdebug("- checking for obsolete APT keyring files")
    for path in (
        DEFAULT_KEYRING_DIR / name for name in OBSOLETE_KEYRING_FILES
    ):
        if path.exists():
            rdebug("  - removing {path}".format(path=path))
            path.unlink()


def stop():
    """ Nothing to do, really. """
    rdebug("storpool-repo-add stopping as requested")
