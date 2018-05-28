"""
A Juju charm layer that installs the `storpool_beacon` service.
"""
from __future__ import print_function

from charms import reactive
from charmhelpers.core import hookenv, host

from spcharms import config as spconfig
from spcharms import error as sperror
from spcharms import repo as sprepo
from spcharms import states as spstates
from spcharms import status as spstatus
from spcharms import utils as sputils

STATES_REDO = {
    'set': [],
    'unset': [
        'storpool-beacon.beacon-started',
    ],
}


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
        'storpool-beacon-' + spmajmin: spver,
    }
    newly_installed = sprepo.install_packages(packages)
    if newly_installed:
        rdebug('it seems we managed to install some packages: {names}'
               .format(names=newly_installed))
        sprepo.record_packages('storpool-beacon', newly_installed)
    else:
        rdebug('it seems that all the packages were installed already')

    spstatus.npset('maintenance', '')


def enable_and_start():
    """
    Enable and start the `storpool_beacon` service.
    May raise a StorPoolNoCGroupsException.
    """
    if sputils.check_in_lxc():
        rdebug('running in an LXC container, not doing anything more')
        reactive.set_state('storpool-beacon.beacon-started')
        return

    sputils.check_cgroups('beacon')

    rdebug('enabling and starting the beacon service')
    host.service_resume('storpool_beacon')
    reactive.set_state('storpool-beacon.beacon-started')


@reactive.when('storpool-helper.config-set')
@reactive.when('storpool-repo-add.available')
@reactive.when('storpool-common.config-written')
@reactive.when_not('storpool-beacon.beacon-started')
@reactive.when_not('storpool-beacon.stopped')
def run():
    try:
        install_package()
        enable_and_start()
    except sperror.StorPoolNoConfigException as e_cfg:
        hookenv.log('beacon: missing configuration: {m}'
                    .format(m=', '.join(e_cfg.missing)),
                    hookenv.INFO)
    except sperror.StorPoolPackageInstallException as e_pkg:
        hookenv.log('beacon: could not install the {names} packages: {e}'
                    .format(names=' '.join(e_pkg.names), e=e_pkg.cause),
                    hookenv.ERROR)
    except sperror.StorPoolNoCGroupsException as e_cfg:
        hookenv.log('beacon: {e}'.format(e=e_cfg), hookenv.ERROR)


@reactive.when('storpool-beacon.beacon-started')
@reactive.when_not('storpool-common.config-written')
@reactive.when_not('storpool-beacon.stopped')
def reinstall():
    """
    Trigger a reinstallation of the `storpool_beacon` package.
    """
    reactive.remove_state('storpool-beacon.beacon-started')


@reactive.hook('install')
def register_states():
    """
    Register for a full reinstall upon an upgrade-charm event.
    """
    spstates.register('storpool-beacon', {'upgrade-charm': STATES_REDO})


@reactive.when('storpool-beacon.stop')
@reactive.when_not('storpool-beacon.stopped')
def remove_leftovers():
    """
    Clean up, disable the service, uninstall the packages.
    """
    rdebug('storpool-beacon.stop invoked')
    reactive.remove_state('storpool-beacon.stop')

    if not sputils.check_in_lxc():
        rdebug('stopping and disabling the storpool_beacon service')
        host.service_pause('storpool_beacon')

        rdebug('uninstalling any beacon-related packages')
        sprepo.unrecord_packages('storpool-beacon')

    rdebug('letting storpool-openstack-integration know')
    reactive.set_state('storpool-osi.stop')

    reactive.set_state('storpool-beacon.stopped')
    for state in STATES_REDO['set'] + STATES_REDO['unset']:
        reactive.remove_state(state)
