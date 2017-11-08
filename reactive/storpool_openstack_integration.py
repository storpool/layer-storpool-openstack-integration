"""
A Juju charm layer that installs the StorPool OpenStack integration into
the current node and, if configured, its LXD containers.
"""
from __future__ import print_function

import os
import platform
import tempfile
import subprocess

from charms import reactive
from charms.reactive import helpers as rhelpers
from charmhelpers.core import hookenv, host, unitdata

from spcharms import config as spconfig
from spcharms import repo as sprepo
from spcharms import status as spstatus
from spcharms import txn
from spcharms import utils as sputils


def block_conffile():
    """
    Return the name of the configuration file that will be generated for
    the `storpool_block` service in order to also export the block devices
    into the host's LXD containers.
    """
    return '/etc/storpool.conf.d/storpool-cinder-block.conf'


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
@reactive.when_not('storpool-osi.installed-into-lxds')
@reactive.when_not('storpool-osi.stopped')
def enable_and_start():
    """
    Run the StorPool OpenStack integration on the current node and,
    if configured, its LXD containers.
    """
    if not hookenv.config()['storpool_openstack_install']:
        rdebug('skipping the installation into containers')
        reactive.set_state('storpool-osi.installed-into-lxds')
        return

    spstatus.npset('maintenance', 'installing the OpenStack integration into '
                   'the running containers')
    rdebug('installing into the running containers')

    sp_ourid = spconfig.get_our_id()
    rdebug('- got SP_OURID {ourid}'.format(ourid=sp_ourid))

    lxd_cinder = None
    nova_found = False
    for lxd in txn.LXD.construct_all():
        rdebug('- trying for "{name}"'.format(name=lxd.name))

        if lxd.name == '':
            rdebug('  - no need to copy packages into "{name}"'
                   .format(name=lxd.name))
        else:
            rdebug('  - copying packages into "{name}"'.format(name=lxd.name))
            lxd.copy_package_trees('storpool-openstack-integration')

        rdebug('  - trying to detect OpenStack components in "{name}"'
               .format(name=lxd.name))
        global openstack_components
        for comp in openstack_components:
            res = lxd.exec_with_output(['sp-openstack', '--', 'detect', comp])
            if res['res'] != 0:
                rdebug('    - {comp} not found'.format(comp=comp))
                continue
            rdebug('    - {comp} FOUND!'.format(comp=comp))

            if comp == 'cinder' and lxd.name != '':
                if lxd_cinder is None:
                    rdebug('     - and it is a Cinder one, stashing it...')
                    lxd_cinder = lxd
                    rdebug('    - and installing /etc/storpool.conf into '
                           '"{name}"'.format(name=lxd.name))
                    lxd.txn.install_exact('/etc/storpool.conf',
                                          '/etc/storpool.conf')
                else:
                    rdebug('     - oof, found two Cinder LXDs, using '
                           '"{first}" and not "{second}"'
                           .format(first=lxd_cinder.name, second=lxd.name))

            if comp == 'nova' and lxd.name == '':
                nova_found = True
                rdebug('     - found Nova on bare metal, will try to '
                       'restart it')

            if lxd.name == '':
                rdebug('    - no need to copy more packages into "{name}"'
                       .format(name=lxd.name))
            else:
                rdebug('    - installing the rest of our packages into '
                       '"{name}"'.format(name=lxd.name))
                lxd.copy_package_trees('txn-install',
                                       'python-storpool-spopenstack')
                rdebug('    - and installing /etc/storpool.conf into "{name}"'
                       .format(name=lxd.name))
                lxd.txn.install_exact('/etc/storpool.conf',
                                      '/etc/storpool.conf')

                cfgdir = '/etc/storpool.conf.d'
                pfxdir = lxd.prefix + cfgdir
                if not os.path.isdir(pfxdir):
                    rdebug('    - and creating the {pfxdir} directory'
                           .format(pfxdir=pfxdir))
                    os.mkdir(pfxdir, mode=0o755)
                cfgname = cfgdir + '/storpool-cinder-ourid.conf'
                rdebug('    - and generating the {cfgname} file in "{name}"'
                       .format(cfgname=cfgname, name=lxd.name))
                with tempfile.NamedTemporaryFile(dir='/tmp',
                                                 mode='w+t') as spouridconf:
                    print('[{name}]\nSP_OURID={ourid}'
                          .format(name=lxd.name, ourid=sp_ourid),
                          file=spouridconf)
                    spouridconf.flush()
                    lxd.txn.install('-o', 'root', '-g', 'root', '-m', '644',
                                    '--', spouridconf.name, cfgname)

            res = lxd.exec_with_output(['sp-openstack', '--', 'check', comp])
            if res['res'] == 0:
                rdebug('    - {comp} integration already there'
                       .format(comp=comp))
            else:
                rdebug('    - {comp} MISSING integration'.format(comp=comp))
                rdebug('    - running sp-openstack install {comp}'
                       .format(comp=comp))
                res = lxd.exec_with_output(['sp-openstack', '-T',
                                            txn.module_name(), '--', 'install',
                                            comp])
                if res['res'] != 0:
                    raise Exception('Could not install the StorPool OpenStack '
                                    'integration for {comp} in the "{name}" '
                                    'container'
                                    .format(comp=comp, name=lxd.name))

            rdebug('    - done with {comp}'.format(comp=comp))

        rdebug('  - done with "{name}"'.format(name=lxd.name))

    rdebug('done with the running containers')

    confname = block_conffile()
    if lxd_cinder is not None:
        rdebug('found a Cinder container at "{name}"'
               .format(name=lxd_cinder.name))
        try:
            rdebug('about to record the name of the Cinder LXD - "{name}" - '
                   'into {confname}'
                   .format(name=lxd_cinder.name, confname=confname))
            dirname = os.path.dirname(confname)
            rdebug('- checking for the {dirname} directory'
                   .format(dirname=dirname))
            if not os.path.isdir(dirname):
                rdebug('  - nah, creating it')
                os.mkdir(dirname, mode=0o755)

            rdebug('- is the file there?')
            okay = False
            expected_contents = [
                '[{node}]'.format(node=platform.node()),
                'SP_EXTRA_FS=lxd:{name}'.format(name=lxd_cinder.name)
            ]
            if os.path.isfile(confname):
                rdebug('  - yes, it is... but does it contain the right data?')
                with open(confname, mode='r') as conffile:
                    contents = list(map(lambda s: s.rstrip(),
                                        conffile.readlines()))
                    if contents == expected_contents:
                        rdebug('   - whee, it already does!')
                        okay = True
                    else:
                        rdebug('   - it does NOT: {lst}'.format(lst=contents))
            else:
                rdebug('   - nah...')
                if os.path.exists(confname):
                    rdebug('     - but it still exists?!')
                    subprocess.call(['rm', '-rf', '--', confname])
                    if os.path.exists(confname):
                        rdebug('     - could not remove it, so leaving it '
                               'alone, I guess')
                        okay = True

            if not okay:
                rdebug('- about to recreate the {confname} file'
                       .format(confname=confname))
                with tempfile.NamedTemporaryFile(dir='/tmp',
                                                 mode='w+t') as spconf:
                    print('\n'.join(expected_contents), file=spconf)
                    spconf.flush()
                    txn.install('-o', 'root', '-g', 'root', '-m', '644', '--',
                                spconf.name, confname)
                rdebug('- looks like we are done with it')
                rdebug('- let us try to restart the storpool_block service '
                       '(it may not even have been started yet, so '
                       'ignore errors)')
                try:
                    if host.service_running('storpool_block'):
                        rdebug('  - well, it does seem to be running, '
                               'so restarting it')
                        host.service_restart('storpool_block')
                    else:
                        rdebug('  - nah, it was not running at all indeed')
                except Exception as e:
                    rdebug('  - could not restart the service, but '
                           'ignoring the error: {e}'.format(e=e))
            unitdata.kv().set('storpool-openstack-integration.lxd-name',
                              lxd_cinder.name)
        except Exception as e:
            rdebug('could not check for and/or recreate the {confname} '
                   'storpool_block config file adapted the "{name}" '
                   'LXD container: {e}'
                   .format(confname=confname, name=lxd_cinder.name, e=e))
    else:
        rdebug('no Cinder LXD containers found, checking for '
               'any previously stored configuration...')
        removed = False
        if os.path.isfile(confname):
            rdebug('- yes, {confname} exists, removing it'
                   .format(confname=confname))
            try:
                os.unlink(confname)
                removed = True
            except Exception as e:
                rdebug('could not remove {confname}: {e}'
                       .format(confname=confname, e=e))
        elif os.path.exists(confname):
            rdebug('- well, {confname} exists, but it is not a file; '
                   'removing it anyway'.format(confname=confname))
            subprocess.call(['rm', '-rf', '--', confname])
            removed = True
        if removed:
            rdebug('- let us try to restart the storpool_block service ' +
                   '(it may not even have been started yet, so ignore errors)')
            try:
                if host.service_running('storpool_block'):
                    rdebug('  - well, it does seem to be running, so ' +
                           'restarting it')
                    host.service_restart('storpool_block')
                else:
                    rdebug('  - nah, it was not running at all indeed')
            except Exception as e:
                rdebug('  - could not restart the service, but '
                       'ignoring the error: {e}'.format(e=e))

    if nova_found:
        rdebug('Found Nova on bare metal, trying to restart nova-compute')
        rdebug('(errors will be ignored)')
        res = subprocess.call(['service', 'nova-compute', 'restart'])
        if res == 0:
            rdebug('Well, looks like it was restarted successfully')
        else:
            rdebug('"service nova-compute restart" returned '
                   'a non-zero exit code {res}, ignoring it'.format(res=res))

    reactive.set_state('storpool-osi.installed-into-lxds')
    spstatus.npset('maintenance', '')


@reactive.when('storpool-osi.installed-into-lxds')
@reactive.when_not('storpool-osi.package-installed')
@reactive.when_not('storpool-osi.stopped')
def restart():
    """
    Rerun the installation of the OpenStack integration.
    """
    reactive.remove_state('storpool-osi.installed-into-lxds')


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
    reactive.remove_state('storpool-osi.installed-into-lxds')


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
