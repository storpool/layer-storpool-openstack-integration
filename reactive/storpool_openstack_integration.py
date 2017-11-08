"""
A Juju charm layer that installs the StorPool OpenStack integration into
the current node and, if configured, its LXD containers.
"""
from __future__ import print_function

import subprocess

from charms import reactive
from charms.reactive import helpers as rhelpers
from charmhelpers.core import hookenv

from spcharms import config as spconfig
from spcharms import repo as sprepo
from spcharms import status as spstatus
from spcharms import txn
from spcharms import utils as sputils


def rdebug(s):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix='openstack-integration')


@reactive.hook('config-changed')
def config_changed():
    """
    Check if all the configuration settings have been supplied and/or changed.
    """
    rdebug('config-changed happened')
    config = hookenv.config()

    spver = config.get('storpool_version', None)
    rdebug('and we do{xnot} have a storpool_version setting'
           .format(xnot=' not' if spver is None else ''))
    sposiver = config.get('storpool_openstack_version', None)
    rdebug('and we do{xnot} have a storpool_openstack_version setting'
           .format(xnot=' not' if sposiver is None else ''))
    if spver is None or spver == '' or sposiver is None or sposiver == '':
        rdebug('removing the config-available state')
        reactive.remove_state('storpool-osi.config-available')
        reactive.remove_state('storpool-osi.package-installed')
        return

    rdebug('setting the config-available state')
    reactive.set_state('storpool-osi.config-available')

    if (config.changed('storpool_version') or
        config.changed('storpool_openstack_version')) and \
       rhelpers.is_state('storpool-osi.package-installed'):
        rdebug('the StorPool component versions have changed, removing '
               'the package-installed state')
        reactive.remove_state('storpool-osi.package-installed')


openstack_components = ['cinder', 'os_brick', 'nova']


@reactive.when('storpool-repo-add.available', 'storpool-common.config-written')
@reactive.when('storpool-osi.config-available')
@reactive.when_not('storpool-osi.package-installed')
@reactive.when_not('storpool-osi.stopped')
def install_package():
    """
    Install the StorPool OpenStack integration Ubuntu packages.
    """
    rdebug('the OpenStack integration repo has become available and '
           'the common packages have been configured')

    spstatus.npset('maintenance', 'obtaining the requested StorPool version')
    spver = hookenv.config().get('storpool_version', None)
    sposiver = hookenv.config().get('storpool_openstack_version', None)
    spinstall = hookenv.config().get('storpool_openstack_install', None)
    if spver is None or spver == '':
        rdebug('no storpool_version key in the charm config yet')
        return
    if sposiver is None or sposiver == '':
        rdebug('no storpool_openstack_version key in the charm config yet')
        return
    if sposiver is None or sposiver == '':
        rdebug('no storpool_openstack_version key in the charm config yet')
        return
    if spinstall is None:
        rdebug('no storpool_openstack_install key in the charm config yet')
        return

    if not spinstall:
        rdebug('skipping the installation of the OpenStack integration')
        reactive.set_state('storpool-osi.package-installed')
        return

    spstatus.npset('maintenance', 'installing the StorPool OpenStack packages')
    (err, newly_installed) = sprepo.install_packages({
        'storpool-block': spver,
        'python-storpool-spopenstack': spver,
        'storpool-openstack-integration': sposiver,
    })
    if err is not None:
        rdebug('oof, we could not install packages: {err}'.format(err=err))
        rdebug('removing the package-installed state')
        return

    if newly_installed:
        rdebug('it seems we managed to install some packages: {names}'
               .format(names=newly_installed))
        sprepo.record_packages('storpool-osi', newly_installed)
    else:
        rdebug('it seems that all the packages were installed already')

    rdebug('setting the package-installed state')
    reactive.set_state('storpool-osi.package-installed')
    spstatus.npset('maintenance', '')


@reactive.when('storpool-osi.package-installed')
@reactive.when_not('storpool-osi.installed')
@reactive.when_not('storpool-osi.stopped')
def enable_and_start():
    """
    Run the StorPool OpenStack integration on the current node and,
    if configured, its LXD containers.
    """
    if not hookenv.config()['storpool_openstack_install']:
        rdebug('skipping the installation into containers')
        reactive.set_state('storpool-osi.installed')
        return

    spstatus.npset('maintenance', 'installing the OpenStack integration into '
                   'the running containers')
    rdebug('installing the StorPool OpenStack integration')

    sp_ourid = spconfig.get_our_id()
    rdebug('- got SP_OURID {ourid}'.format(ourid=sp_ourid))

    nova_found = False
    rdebug('- trying to detect OpenStack components')
    for comp in openstack_components:
        res = sputils.exec(['sp-openstack', '--', 'detect', comp])
        if res['res'] != 0:
            rdebug('    - {comp} not found'.format(comp=comp))
            continue
        rdebug('    - {comp} FOUND!'.format(comp=comp))

        if comp == 'nova':
            nova_found = True
            rdebug('     - found Nova on bare metal, will try to restart it')

        res = sputils.exec(['sp-openstack', '--', 'check', comp])
        if res['res'] == 0:
            rdebug('    - {comp} integration already there'
                   .format(comp=comp))
        else:
            rdebug('    - {comp} MISSING integration'.format(comp=comp))
            rdebug('    - running sp-openstack install {comp}'
                   .format(comp=comp))
            res = sputils.exec(['sp-openstack', '-T',
                                txn.module_name(), '--', 'install',
                                comp])
            if res['res'] != 0:
                raise Exception('Could not install the StorPool OpenStack '
                                'integration for {comp}'.format(comp=comp))

        rdebug('    - done with {comp}'.format(comp=comp))

    rdebug('done with the OpenStack components')

    if nova_found:
        rdebug('Found Nova on bare metal, trying to restart nova-compute')
        rdebug('(errors will be ignored)')
        res = subprocess.call(['service', 'nova-compute', 'restart'])
        if res == 0:
            rdebug('Well, looks like it was restarted successfully')
        else:
            rdebug('"service nova-compute restart" returned '
                   'a non-zero exit code {res}, ignoring it'.format(res=res))

    reactive.set_state('storpool-osi.installed')
    spstatus.npset('maintenance', '')


@reactive.when('storpool-osi.installed')
@reactive.when_not('storpool-osi.package-installed')
@reactive.when_not('storpool-osi.stopped')
def restart():
    """
    Rerun the installation of the OpenStack integration.
    """
    reactive.remove_state('storpool-osi.installed')


@reactive.when('storpool-osi.package-installed')
@reactive.when_not('storpool-common.config-written')
@reactive.when_not('storpool-osi.stopped')
def reinstall():
    """
    Rerun both the package installation and the configuration itself.
    """
    reactive.remove_state('storpool-osi.package-installed')


def reset_states():
    """
    Rerun everything.
    """
    rdebug('state reset requested')
    spstatus.reset_unless_error()
    reactive.remove_state('storpool-osi.package-installed')
    reactive.remove_state('storpool-osi.installed')


@reactive.hook('upgrade-charm')
def remove_states_on_upgrade():
    """
    Rerun everything on charm upgrade.
    """
    rdebug('storpool-osi.upgrade-charm invoked')
    reset_states()


@reactive.when('storpool-osi.stop')
@reactive.when_not('storpool-osi.stopped')
def remove_leftovers():
    """
    Clean up on deinstallation.
    If the "storpool-osi.no-propagate-stop" reactive state is set,
    do not set the "stop" states for the lower layers; the uppper layers or
    charms have taken care of that.
    """
    rdebug('storpool-osi.stop invoked')
    reactive.remove_state('storpool-osi.stop')

    rdebug('uninstalling any OpenStack-related StorPool packages')
    sprepo.unrecord_packages('storpool-osi')

    if not rhelpers.is_state('storpool-osi.no-propagate-stop'):
        rdebug('letting storpool-common know')
        reactive.set_state('storpool-common.stop')
    else:
        rdebug('apparently someone else will/has let storpool-common know')

    reset_states()
    reactive.set_state('storpool-osi.stopped')
