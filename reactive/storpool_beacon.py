"""
A Juju charm layer that installs the `storpool_beacon` service.
"""
from __future__ import print_function

from charms import reactive
from charmhelpers.core import host

from spcharms import config as spconfig
from spcharms import repo as sprepo
from spcharms import states as spstates
from spcharms import status as spstatus
from spcharms import utils as sputils

STATES_REDO = {
    'set': [],
    'unset': [
        'storpool-beacon.package-installed',
        'storpool-beacon.beacon-started',
    ],
}


def rdebug(s):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix='beacon')


@reactive.when('storpool-helper.config-set')
@reactive.when('storpool-repo-add.available')
@reactive.when('storpool-common.config-written')
@reactive.when_not('storpool-beacon.package-installed')
@reactive.when_not('storpool-beacon.stopped')
def install_package():
    """
    Install the `storpool_beacon` package.
    """
    rdebug('the beacon repo has become available and '
           'the common packages have been configured')
    if sputils.check_in_lxc():
        rdebug('running in an LXC container, not doing anything more')
        reactive.set_state('storpool-beacon.package-installed')
        return

    spstatus.npset('maintenance', 'obtaining the requested StorPool version')
    spver = spconfig.m().get('storpool_version', None)
    if spver is None or spver == '':
        rdebug('no storpool_version key in the charm config yet')
        return

    spstatus.npset('maintenance', 'installing the StorPool beacon packages')
    (err, newly_installed) = sprepo.install_packages({
        'storpool-beacon': spver,
    })
    if err is not None:
        rdebug('oof, we could not install packages: {err}'.format(err=err))
        rdebug('removing the package-installed state')
        return

    if newly_installed:
        rdebug('it seems we managed to install some packages: {names}'
               .format(names=newly_installed))
        sprepo.record_packages('storpool-beacon', newly_installed)
    else:
        rdebug('it seems that all the packages were installed already')

    rdebug('setting the package-installed state')
    reactive.set_state('storpool-beacon.package-installed')
    spstatus.npset('maintenance', '')


@reactive.when('storpool-beacon.package-installed')
@reactive.when_not('storpool-beacon.beacon-started')
@reactive.when_not('storpool-beacon.stopped')
def enable_and_start():
    """
    Enable and start the `storpool_beacon` service.
    """
    if sputils.check_in_lxc():
        rdebug('running in an LXC container, not doing anything more')
        reactive.set_state('storpool-beacon.beacon-started')
        return

    if not sputils.check_cgroups('beacon'):
        return

    rdebug('enabling and starting the beacon service')
    host.service_resume('storpool_beacon')
    reactive.set_state('storpool-beacon.beacon-started')


@reactive.when('storpool-beacon.beacon-started')
@reactive.when_not('storpool-beacon.package-installed')
@reactive.when_not('storpool-beacon.stopped')
def restart():
    """
    Trigger a restart of the `storpool_beacon` service.
    """
    reactive.remove_state('storpool-beacon.beacon-started')


@reactive.when('storpool-beacon.package-installed')
@reactive.when_not('storpool-common.config-written')
@reactive.when_not('storpool-beacon.stopped')
def reinstall():
    """
    Trigger a reinstallation of the `storpool_beacon` package.
    """
    reactive.remove_state('storpool-beacon.package-installed')


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

    rdebug('letting storpool-common know')
    reactive.set_state('storpool-common.stop')

    reactive.set_state('storpool-beacon.stopped')
    for state in STATES_REDO['set'] + STATES_REDO['unset']:
        reactive.remove_state(state)
