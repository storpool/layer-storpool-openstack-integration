"""
A Juju charm layer that installs and starts the StorPool block (client)
service from the StorPool Ubuntu package repository.
"""
from __future__ import print_function

import os.path
import subprocess

from charms import reactive
from charmhelpers.core import host

from spcharms import config as spconfig
from spcharms import error as sperror
from spcharms import repo as sprepo
from spcharms import status as spstatus
from spcharms import utils as sputils

from spcharms.run import storpool_beacon as run_beacon


def rdebug(s):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix="block")


def install_package():
    """
    Install the StorPool block package.
    May raise a StorPoolNoConfigException or a StorPoolPackageInstallException.
    """
    rdebug(
        "the block repo has become available and the common packages "
        "have been configured"
    )

    if sputils.check_in_lxc():
        rdebug("running in an LXC container, not doing anything more")
        return

    spstatus.npset("maintenance", "obtaining the requested StorPool version")
    spver = spconfig.m().get("storpool_version", None)
    if spver is None or spver == "":
        raise sperror.StorPoolNoConfigException(["storpool_version"])
    spmajmin = ".".join(spver.split(".")[0:2])

    spstatus.npset("maintenance", "installing the StorPool block packages")
    packages = {"storpool-block-" + spmajmin: "*"}
    newly_installed = sprepo.install_packages(packages)
    if newly_installed:
        reactive.set_state("storpool-block.need-update-rdma")
        rdebug(
            "it seems we managed to install some packages: {names}".format(
                names=newly_installed
            )
        )
        sprepo.record_packages("storpool-block", newly_installed)
    else:
        rdebug("it seems that all the packages were installed already")

    if reactive.is_state("storpool-block.need-update-rdma"):
        reactive.remove_state("storpool-block.need-update-rdma")
        rdebug("reloading the systemd database (errors ignored)")
        subprocess.call(["systemctl", "daemon-reload"])
        rdebug("reloading the StorPool kernel modules (errors ignored)")
        subprocess.call(["/usr/lib/storpool/update_rdma", "--yes"])
    else:
        rdebug("no reload needed")

    spstatus.npset("maintenance", "")


def enable_and_start():
    """
    Start the `storpool_block` service.
    May raise a StorPoolNoCGroupsException.
    """
    if sputils.check_in_lxc():
        rdebug("running in an LXC container, not doing anything more")
        return

    sputils.check_cgroups("block")

    rdebug("enabling and starting the block service")
    host.service_resume("storpool_block")
    if os.path.isfile("/usr/sbin/storpool_stat.bin"):
        host.service_resume("storpool_stat")


def run():
    """
    Invoke install_package() and enable_and_start() as needed.
    """
    reactive.remove_state("storpool-block.need-update-rdma")
    rdebug("Run, beacon, run!")
    run_beacon.run()
    rdebug("Returning to the storpool_block setup")
    install_package()
    enable_and_start()


def stop():
    """
    Remove the installed packages and stop the service.
    """
    rdebug("storpool-block.stop invoked")

    if not sputils.check_in_lxc():
        rdebug("stopping and disabling the storpool_block service")
        host.service_pause("storpool_block")

        rdebug("uninstalling any block-related packages")
        sprepo.unrecord_packages("storpool-block")

    rdebug("let storpool-beacon know")
    run_beacon.stop()
