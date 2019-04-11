"""
A Juju charm layer that installs the `storpool_beacon` service.
"""
from __future__ import print_function

import subprocess

from charmhelpers.core import host

from spcharms import config as spconfig
from spcharms import error as sperror
from spcharms import repo as sprepo
from spcharms import status as spstatus
from spcharms import utils as sputils

from spcharms.run import storpool_openstack_integration as run_osi


def rdebug(s):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix='beacon')


def install_package():
    """
    Install the `storpool_beacon` package.
    May raise a StorPoolNoConfigException or a StorPoolPackageInstallException.
    """
    rdebug('the beacon repo has become available and '
           'the common packages have been configured')
    if sputils.check_in_lxc():
        rdebug('running in an LXC container, not doing anything more')
        return

    spstatus.npset('maintenance', 'obtaining the requested StorPool version')
    spver = spconfig.m().get('storpool_version', None)
    if spver is None or spver == '':
        raise sperror.StorPoolNoConfigException(['storpool_version'])
    spmajmin = '.'.join(spver.split('.')[0:2])

    spstatus.npset('maintenance', 'installing the StorPool beacon packages')
    packages = {
        'storpool-beacon-' + spmajmin: '*',
    }
    newly_installed = sprepo.install_packages(packages)
    if newly_installed:
        rdebug('it seems we managed to install some packages: {names}'
               .format(names=newly_installed))
        sprepo.record_packages('storpool-beacon', newly_installed)

        rdebug('reloading the systemd database (errors ignored)')
        subprocess.call(['systemctl', 'daemon-reload'])
        rdebug('reloading the StorPool kernel modules (errors ignored)')
        subprocess.call(['/usr/lib/storpool/update_rdma', '--yes'])
    else:
        rdebug('it seems that all the packages were installed already')

    if spmajmin != '18.01':
        rdebug('starting storpool_hugepages')
        subprocess.check_call(['storpool_hugepages', '-v'])
        rdebug('enabling and starting the storpool_hugepages service')
        host.service_resume('storpool_hugepages')
    else:
        rdebug('skipping storpool_hugepages on StorPool 18.01')

    spstatus.npset('maintenance', '')


def enable_and_start():
    """
    Enable and start the `storpool_beacon` service.
    May raise a StorPoolNoCGroupsException.
    """
    if sputils.check_in_lxc():
        rdebug('running in an LXC container, not doing anything more')
        return

    sputils.check_cgroups('beacon')

    rdebug('enabling and starting the beacon service')
    host.service_resume('storpool_beacon')


def run():
    rdebug('Run, OpenStack integration, run!')
    run_osi.run()
    rdebug('Returning to the storpool-beacon setup')
    install_package()
    enable_and_start()


def stop():
    """
    Clean up, disable the service, uninstall the packages.
    """
    rdebug('storpool-beacon.stop invoked')

    if not sputils.check_in_lxc():
        rdebug('stopping and disabling the storpool_beacon service')
        host.service_pause('storpool_beacon')

        rdebug('uninstalling any beacon-related packages')
        sprepo.unrecord_packages('storpool-beacon')

    rdebug('letting storpool-openstack-integration know')
    run_osi.stop()
