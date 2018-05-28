"""
A Juju charm layer that installs and starts the StorPool block (client)
service from the StorPool Ubuntu package repository.
"""
from __future__ import print_function

import os.path

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
        'storpool-block.package-installed',
        'storpool-block.block-started',
    ],
}


def rdebug(s):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix='block')


@reactive.when('storpool-helper.config-set')
@reactive.when('storpool-repo-add.available')
@reactive.when('storpool-common.config-written')
@reactive.when_not('storpool-block.package-installed')
@reactive.when_not('storpool-block.stopped')
def install_package():
    """
    Install the StorPool block package.
    """
    rdebug('the block repo has become available and the common packages '
           'have been configured')

    if sputils.check_in_lxc():
        rdebug('running in an LXC container, not doing anything more')
        reactive.set_state('storpool-block.package-installed')
        return

    spstatus.npset('maintenance', 'obtaining the requested StorPool version')
    spver = spconfig.m().get('storpool_version', None)
    if spver is None or spver == '':
        rdebug('no storpool_version key in the charm config yet')
        return
    spmajmin = '.'.join(spver.split('.')[0:2])

    spstatus.npset('maintenance', 'installing the StorPool block packages')
    (err, newly_installed) = sprepo.install_packages({
        'storpool-block-' + spmajmin: spver,
    })
    if err is not None:
        rdebug('oof, we could not install packages: {err}'.format(err=err))
        rdebug('removing the package-installed state')
        return

    if newly_installed:
        rdebug('it seems we managed to install some packages: {names}'
               .format(names=newly_installed))
        sprepo.record_packages('storpool-block', newly_installed)
    else:
        rdebug('it seems that all the packages were installed already')

    rdebug('setting the package-installed state')
    reactive.set_state('storpool-block.package-installed')
    spstatus.npset('maintenance', '')


@reactive.when('storpool-block.package-installed')
@reactive.when('storpool-beacon.beacon-started')
@reactive.when_not('storpool-block.block-started')
@reactive.when_not('storpool-block.stopped')
def enable_and_start():
    """
    Start the `storpool_block` service.
    """
    if sputils.check_in_lxc():
        rdebug('running in an LXC container, not doing anything more')
        reactive.set_state('storpool-block.block-started')
        return

    if not sputils.check_cgroups('block'):
        return

    rdebug('enabling and starting the block service')
    host.service_resume('storpool_block')
    if os.path.isfile('/usr/sbin/storpool_stat.bin'):
        host.service_resume('storpool_stat')
    reactive.set_state('storpool-block.block-started')


@reactive.when('storpool-block.block-started')
@reactive.when_not('storpool-block.package-installed')
@reactive.when_not('storpool-block.stopped')
def restart():
    """
    Trigger a restart of the `storpool_block` service.
    """
    reactive.remove_state('storpool-block.block-started')


@reactive.when('storpool-block.package-installed')
@reactive.when_not('storpool-common.config-written')
@reactive.when_not('storpool-block.stopped')
def reinstall():
    """
    Trigger a reinstall and restart of the `storpool_block` service.
    """
    reactive.remove_state('storpool-block.package-installed')


@reactive.hook('install')
def register():
    """
    Register our hook state mapping.
    """
    spstates.register('storpool-block', {'upgrade-charm': STATES_REDO})


@reactive.when('storpool-block.stop')
@reactive.when_not('storpool-block.stopped')
def remove_leftovers():
    """
    Remove the installed packages and stop the service.
    """
    rdebug('storpool-block.stop invoked')
    reactive.remove_state('storpool-block.stop')

    if not sputils.check_in_lxc():
        rdebug('stopping and disabling the storpool_block service')
        host.service_pause('storpool_block')

        rdebug('uninstalling any block-related packages')
        sprepo.unrecord_packages('storpool-block')

    rdebug('let storpool-beacon know')
    reactive.set_state('storpool-beacon.stop')

    reactive.set_state('storpool-block.stopped')
    for state in STATES_REDO['set'] + STATES_REDO['unset']:
        reactive.remove_state(state)
