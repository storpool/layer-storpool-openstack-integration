"""
A Juju charm layer that installs the StorPool OpenStack integration into
the current node and, if configured, its LXD containers.
"""
from __future__ import print_function

import subprocess

from charmhelpers.core import hookenv

from spcharms import config as spconfig
from spcharms import error as sperror
from spcharms import repo as sprepo
from spcharms import status as spstatus
from spcharms import txn
from spcharms import utils as sputils

from spcharms.run import storpool_common as run_common


def rdebug(s):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix='openstack-integration')


def config_changed():
    """
    Check if all the configuration settings have been supplied and/or changed.
    """
    rdebug('config-changed happened')
    config = spconfig.m()

    spver = config.get('storpool_version', None)
    rdebug('and we do{xnot} have a storpool_version setting'
           .format(xnot=' not' if spver is None else ''))
    sposiver = config.get('storpool_openstack_version', None)
    rdebug('and we do{xnot} have a storpool_openstack_version setting'
           .format(xnot=' not' if sposiver is None else ''))
    no_spver = spver is None or spver == ''
    no_sposiver = sposiver is None or sposiver == ''
    if no_spver:
        raise sperror.StorPoolNoConfigException(['storpool_version'])
    if no_sposiver:
        raise sperror.StorPoolNoConfigException(['storpool_openstack_version'])


openstack_components = ['cinder', 'os_brick', 'nova']


def install_package():
    """
    Install the StorPool OpenStack integration Ubuntu packages.
    """
    rdebug('the OpenStack integration repo has become available and '
           'the common packages have been configured')

    config = spconfig.m()
    spstatus.npset('maintenance', 'obtaining the requested StorPool version')
    spver = config.get('storpool_version', None)
    sposiver = config.get('storpool_openstack_version', None)
    # Specifically get this one from the charm's config, not from
    # whatever another charm happened to pass down.
    spinstall = hookenv.config().get('storpool_openstack_install', None)
    if spver is None or spver == '':
        raise sperror.StorPoolNoConfigException(['storpool_version'])
    if sposiver is None or sposiver == '':
        raise sperror.StorPoolNoConfigException(['storpool_openstack_version'])
    if spinstall is None:
        raise sperror.StorPoolNoConfigException(['storpool_openstack_install'])
    spmajmin = '.'.join(spver.split('.')[0:2])

    if not spinstall:
        rdebug('skipping the installation of the OpenStack integration')
        return

    spstatus.npset('maintenance', 'installing the StorPool OpenStack packages')
    packages = {
        'storpool-block-' + spmajmin: '*',
        'python-storpool-spopenstack-' + spmajmin: '*',
        'storpool-openstack-integration': sposiver,
    }
    newly_installed = sprepo.install_packages(packages)
    if newly_installed:
        rdebug('it seems we managed to install some packages: {names}'
               .format(names=newly_installed))
        sprepo.record_packages('storpool-osi', newly_installed)
    else:
        rdebug('it seems that all the packages were installed already')

    spstatus.npset('maintenance', '')


def enable_and_start():
    """
    Run the StorPool OpenStack integration on the current node and,
    if configured, its LXD containers.
    """
    if not hookenv.config()['storpool_openstack_install']:
        rdebug('skipping the installation into containers')
        return

    spstatus.npset('maintenance', 'installing the OpenStack integration into '
                   'the running containers')
    rdebug('installing the StorPool OpenStack integration')

    sp_ourid = spconfig.get_our_id()
    rdebug('- got SP_OURID {ourid}'.format(ourid=sp_ourid))

    spe = sperror.StorPoolException
    restart = {}
    rdebug('- trying to detect OpenStack components')
    safe_path = ['env', 'PATH=/usr/sbin:/usr/bin:/sbin:/bin']
    check_groups = []
    for comp in openstack_components:
        res = sputils.exec(safe_path + ['sp-openstack', '--', 'detect', comp])
        if res['res'] != 0:
            rdebug('    - {comp} not found'.format(comp=comp))
            continue
        rdebug('    - {comp} FOUND!'.format(comp=comp))

        if comp == 'nova':
            restart[comp] = True
            rdebug('     - found Nova on bare metal, will try to restart it')

        if comp in ('cinder', 'nova'):
            check_groups.append(comp)
            rdebug('     - will recheck the spool dir and groups')

        res = sputils.exec(safe_path + ['sp-openstack', '--', 'check', comp])
        if res['res'] == 0:
            rdebug('    - {comp} integration already there'
                   .format(comp=comp))
        else:
            rdebug('    - {comp} MISSING integration'.format(comp=comp))
            rdebug('    - running sp-openstack install {comp}'
                   .format(comp=comp))
            res = sputils.exec(safe_path +
                               ['sp-openstack', '-T',
                                txn.module_name(), '--', 'install',
                                comp])
            if res['res'] != 0:
                raise spe('Could not install the StorPool OpenStack '
                          'integration for {comp}'.format(comp=comp))
            restart[comp] = True

        rdebug('    - done with {comp}'.format(comp=comp))

    rdebug('done with the OpenStack components')

    if check_groups:
        rdebug('Found interesting components, checking the group membership')
        res = sputils.exec(safe_path +
                           ['sp-openstack', '-T',
                            txn.module_name(), '--', 'groups'] + check_groups)
        if res['res'] != 0:
            raise spe('Could not setup the StorPool OpenStack '
                      'groups for {grps}'.format(grps=check_groups))

        # Make sure the service accounts are also in the "disk" group.
        for comp in check_groups:
            out = subprocess.check_output(['id', '-Gn', '--', comp])
            lines = out.decode().strip().split('\n')
            if len(lines) != 1:
                raise spe(
                    'Could not check whether the {comp} account is in '
                    'the "disk" group: unexpected "id -Gn" output: {lines}'
                    .format(comp=comp, lines=lines))
            groups = lines[0].split(' ')
            if 'disk' not in lines[0].split(' '):
                rdebug('Adding the {comp} service account to the "disk" group'
                       .format(comp=comp))
                groups.append('disk')
                subprocess.check_call(['usermod', '-G', ','.join(groups),
                                       '--', comp])
                restart[comp] = True

    service_names = {
        'cinder': 'cinder-volume',
        'nova': 'nova-compute',
        'os_brick': None,
    }
    for comp in sorted(restart.keys()):
        svc = service_names[comp]
        if svc is None:
            rdebug('Nothing to restart for {comp}'.format(comp=comp))
            continue
        rdebug('Restarting the {svc} service (errors will be ignored)'
               .format(svc=svc))
        subprocess.call(['systemctl', 'restart', svc])

    spstatus.npset('maintenance', '')


def run():
    rdebug('Run, common, run!')
    run_common.run()
    rdebug('Returning to the StorPool OpenStack integration setup')
    config_changed()
    install_package()
    enable_and_start()


def stop():
    """
    Clean up on deinstallation.
    """
    rdebug('storpool-osi.stop invoked')

    rdebug('uninstalling any OpenStack-related StorPool packages')
    sprepo.unrecord_packages('storpool-osi')

    rdebug('letting storpool-common know')
    run_common.stop()
