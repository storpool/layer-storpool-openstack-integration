"""
A Juju layer for installing and configuring the base StorPool packages.
"""
from __future__ import print_function

import tempfile
import subprocess

from charms import reactive
from charmhelpers.core import templating

from spcharms import config as spconfig
from spcharms.confighelpers import network as spcnetwork
from spcharms import error as sperror
from spcharms import repo as sprepo
from spcharms import status as spstatus
from spcharms import txn
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
    config = spconfig.m()

    # Remove any states that say we have accomplished anything...
    spconfig.unset_our_id()

    spconf = config.get("storpool_conf", None)
    rdebug(
        "and we do{xnot} have a storpool_conf setting".format(
            xnot=" not" if spconf is None else ""
        )
    )
    if spconf is None or spconf == "":
        raise sperror.StorPoolNoConfigException(["storpool_conf"])

    # This will probably race with some others, but oh well
    spstatus.npset(
        "maintenance",
        "waiting for the StorPool charm configuration and "
        "the StorPool repo setup",
    )


def install_package():
    """
    Install the base StorPool packages.
    """
    rdebug(
        "the repo hook has become available and "
        "we do have the configuration"
    )

    spstatus.npset("maintenance", "obtaining the requested StorPool version")
    spver = spconfig.m().get("storpool_version", None)
    if spver is None or spver == "":
        rdebug("no storpool_version key in the charm config yet")
        return
    spmajmin = ".".join(spver.split(".")[0:2])

    spstatus.npset(
        "maintenance", "installing the StorPool configuration packages"
    )
    packages = {
        "confget": "*",
        "txn-install": "*",
        "storpool-config-" + spmajmin: "*",
        "netplan-parser": "*",
    }
    newly_installed = sprepo.install_packages(packages)
    if newly_installed:
        rdebug(
            "it seems we managed to install some packages: {names}".format(
                names=newly_installed
            )
        )
        sprepo.record_packages("storpool-config", newly_installed)

        for pkg in newly_installed:
            if pkg.startswith("storpool-block-"):
                rdebug("scheduling update_rdma for storpool-block")
                reactive.set_state("storpool-block.need-update-rdma")
            elif pkg.startswith("storpool-beacon-"):
                rdebug("scheduling update_rdma for storpool-beacon")
                reactive.set_state("storpool-beacon.need-update-rdma")
    else:
        rdebug("it seems that all the packages were installed already")

    spstatus.npset("maintenance", "")


def write_out_config():
    """
    Write out the StorPool configuration file specified in the charm config.
    """
    rdebug("about to write out the /etc/storpool.conf file")
    spstatus.npset("maintenance", "updating the /etc/storpool.conf file")
    with tempfile.NamedTemporaryFile(
        dir="/tmp", mode="w+t", delete=True
    ) as spconf:
        rdebug(
            "about to write the contents to the temporary file {sp}".format(
                sp=spconf.name
            ),
            cond="run-config",
        )
        templating.render(
            source="storpool.conf",
            target=spconf.name,
            owner="root",
            perms=0o600,
            context={"storpool_conf": spconfig.m()["storpool_conf"]},
        )
        rdebug("about to invoke txn install", cond="run-config")
        txn.install(
            "-o",
            "root",
            "-g",
            "root",
            "-m",
            "644",
            "--",
            spconf.name,
            "/etc/storpool.conf",
        )
        rdebug(
            "it seems that /etc/storpool.conf has been created",
            cond="run-config",
        )

        rdebug("trying to read it now", cond="run-config")
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


def setup_interfaces():
    """
    Set up the IPv4 addresses of some interfaces if requested.
    """
    if sputils.check_in_lxc():
        rdebug("running in an LXC container, not setting up interfaces")
        return

    rdebug("trying to parse the StorPool interface configuration")
    spstatus.npset(
        "maintenance", "parsing the StorPool interface configuration"
    )
    cfg = spconfig.get_dict()
    ifaces = cfg.get("SP_IFACE", None)
    if ifaces is None:
        raise sperror.StorPoolException("No SP_IFACES in the StorPool config")
    rdebug("got interfaces: {ifaces}".format(ifaces=ifaces))

    spcnetwork.fixup_interfaces(ifaces)

    rdebug("well, looks like it is all done...")
    spstatus.npset("maintenance", "")


def run():
    rdebug("Run, repo, run!")
    run_repo.run()
    rdebug("Returning to the storpool-config setup")
    config_changed()
    install_package()
    write_out_config()
    # setup_interfaces()


def stop():
    """
    Clean up, remove configuration files, uninstall packages.
    """
    rdebug("storpool-config.stop invoked")

    try:
        rdebug("about to roll back any txn-installed files")
        txn.rollback_if_needed()
    except Exception as e:
        rdebug("Could not run txn rollback: {e}".format(e=e))

    if not sputils.check_in_lxc():
        try:
            rdebug("about to remove any loaded kernel modules")

            mods_b = subprocess.check_output(["lsmod"])
            for module_data in mods_b.decode().split("\n"):
                module = module_data.split(" ", 1)[0]
                if not module.startswith("storpool_"):
                    continue
                rdebug("- trying to remove {mod}".format(mod=module))
                subprocess.call(["rmmod", module])

            # Any remaining? (not an error, just, well...)
            rdebug("checking for any remaining StorPool modules")
            remaining = []
            mods_b = subprocess.check_output(["lsmod"])
            for module_data in mods_b.decode().split("\n"):
                module = module_data.split(" ", 1)[0]
                if module.startswith("storpool_"):
                    remaining.append(module)
            if remaining:
                rdebug(
                    "some modules were left over: {lst}".format(
                        lst=" ".join(sorted(remaining))
                    )
                )
            else:
                rdebug("looks like we got rid of them all!")

            rdebug("that is all for the modules")
        except Exception as e:
            rdebug("Could not remove kernel modules: {e}".format(e=e))

    rdebug("removing any config-related packages")
    sprepo.unrecord_packages("storpool-config")

    rdebug("let the storpool-repo layer know that we are shutting down")
    run_repo.stop()
