"""
A Juju layer for installing and configuring the base StorPool packages.
"""
from __future__ import print_function

import tempfile
import subprocess

from charms import reactive
from charmhelpers.core import hookenv, templating

from spcharms import config as spconfig
from spcharms.confighelpers import network as spcnetwork
from spcharms import error as sperror
from spcharms import repo as sprepo
from spcharms import states as spstates
from spcharms import status as spstatus
from spcharms import txn
from spcharms import utils as sputils

STATES_REDO = {
    'set': [],
    'unset': [
        'l-storpool-config.config-network',
    ],
}


def rdebug(s):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix='config')


@reactive.hook('install')
def register():
    """
    Register our hook state mappings.
    """
    spstates.register('storpool-config', {
        'config-changed': STATES_REDO,
        'upgrade-charm': STATES_REDO,
    })


def config_changed():
    """
    Check if the configuration is complete or has been changed.
    """
    rdebug('config-changed happened')
    config = spconfig.m()

    # Remove any states that say we have accomplished anything...
    for state in STATES_REDO['unset']:
        reactive.remove_state(state)
    spconfig.unset_our_id()

    spconf = config.get('storpool_conf', None)
    rdebug('and we do{xnot} have a storpool_conf setting'
           .format(xnot=' not' if spconf is None else ''))
    if spconf is None or spconf == '':
        raise sperror.StorPoolNoConfigException(['storpool_conf'])

    # This will probably race with some others, but oh well
    spstatus.npset('maintenance',
                   'waiting for the StorPool charm configuration and '
                   'the StorPool repo setup')


def install_package():
    """
    Install the base StorPool packages.
    """
    rdebug('the repo hook has become available and '
           'we do have the configuration')

    spstatus.npset('maintenance', 'obtaining the requested StorPool version')
    spver = spconfig.m().get('storpool_version', None)
    if spver is None or spver == '':
        rdebug('no storpool_version key in the charm config yet')
        return
    spmajmin = '.'.join(spver.split('.')[0:2])

    spstatus.npset('maintenance',
                   'installing the StorPool configuration packages')
    packages = {
        'txn-install': '*',
        'storpool-config-' + spmajmin: spver,
    }
    (err, newly_installed) = sprepo.install_packages(packages)
    if err is not None:
        # FIXME: sprepo.install_packages() should do that
        raise sperror.StorPoolPackageInstallException(packages.keys(), err)

    if newly_installed:
        rdebug('it seems we managed to install some packages: {names}'
               .format(names=newly_installed))
        sprepo.record_packages('storpool-config', newly_installed)
    else:
        rdebug('it seems that all the packages were installed already')

    spstatus.npset('maintenance', '')


def write_out_config():
    """
    Write out the StorPool configuration file specified in the charm config.
    """
    rdebug('about to write out the /etc/storpool.conf file')
    spstatus.npset('maintenance', 'updating the /etc/storpool.conf file')
    with tempfile.NamedTemporaryFile(dir='/tmp',
                                     mode='w+t',
                                     delete=True) as spconf:
        rdebug('about to write the contents to the temporary file {sp}'
               .format(sp=spconf.name))
        templating.render(source='storpool.conf',
                          target=spconf.name,
                          owner='root',
                          perms=0o600,
                          context={
                           'storpool_conf': spconfig.m()['storpool_conf'],
                          },
                          )
        rdebug('about to invoke txn install')
        txn.install('-o', 'root', '-g', 'root', '-m', '644', '--',
                    spconf.name, '/etc/storpool.conf')
        rdebug('it seems that /etc/storpool.conf has been created')

        rdebug('trying to read it now')
        spconfig.drop_cache()
        cfg = spconfig.get_dict()
        oid = cfg['SP_OURID']
        spconfig.set_our_id(oid)
        rdebug('got {len} keys in the StorPool config, our id is {oid}'
               .format(len=len(cfg), oid=oid))

    rdebug('setting the config-written state')
    spstatus.npset('maintenance', '')


def setup_interfaces():
    """
    Set up the IPv4 addresses of some interfaces if requested.
    """
    if sputils.check_in_lxc():
        rdebug('running in an LXC container, not setting up interfaces')
        reactive.set_state('l-storpool-config.config-network')
        return

    rdebug('trying to parse the StorPool interface configuration')
    spstatus.npset('maintenance',
                   'parsing the StorPool interface configuration')
    cfg = spconfig.get_dict()
    ifaces = cfg.get('SP_IFACE', None)
    if ifaces is None:
        raise sperror.StorPoolException('No SP_IFACES in the StorPool config')
    rdebug('got interfaces: {ifaces}'.format(ifaces=ifaces))

    spcnetwork.fixup_interfaces(ifaces)

    rdebug('well, looks like it is all done...')
    reactive.set_state('l-storpool-config.config-network')
    spstatus.npset('maintenance', '')


@reactive.when('storpool-helper.config-set')
@reactive.when('storpool-repo-add.available')
@reactive.when_not('l-storpool-config.config-network')
@reactive.when_not('l-storpool-config.stopped')
def run():
    try:
        config_changed()
        install_package()
        write_out_config()
        setup_interfaces()
    except sperror.StorPoolNoConfigException as e_cfg:
        hookenv.log('config: missing configuration: {m}'
                    .format(m=', '.join(e_cfg.missing)),
                    hookenv.INFO)
    except sperror.StorPoolPackageInstallException as e_pkg:
        hookenv.log('config: could not install the {names} packages: {e}'
                    .format(names=' '.join(e_pkg.names), e=e_pkg.cause),
                    hookenv.ERROR)
    except sperror.StorPoolNoCGroupsException as e_cfg:
        hookenv.log('config: unconfigured control groups: {m}'
                    .format(m=', '.join(e_cfg.missing)),
                    hookenv.ERROR)
    except sperror.StorPoolException as e:
        hookenv.log('config: StorPool installation problem: {e}'.format(e=e))


@reactive.when('l-storpool-config.stop')
@reactive.when_not('l-storpool-config.stopped')
def remove_leftovers():
    """
    Clean up, remove configuration files, uninstall packages.
    """
    rdebug('storpool-config.stop invoked')
    reactive.remove_state('l-storpool-config.stop')

    try:
        rdebug('about to roll back any txn-installed files')
        txn.rollback_if_needed()
    except Exception as e:
        rdebug('Could not run txn rollback: {e}'.format(e=e))

    if not sputils.check_in_lxc():
        try:
            rdebug('about to remove any loaded kernel modules')

            mods_b = subprocess.check_output(['lsmod'])
            for module_data in mods_b.decode().split('\n'):
                module = module_data.split(' ', 1)[0]
                rdebug('- got module {mod}'.format(mod=module))
                if module.startswith('storpool_'):
                    rdebug('  - trying to remove it')
                    subprocess.call(['rmmod', module])

            # Any remaining? (not an error, just, well...)
            rdebug('checking for any remaining StorPool modules')
            remaining = []
            mods_b = subprocess.check_output(['lsmod'])
            for module_data in mods_b.decode().split('\n'):
                module = module_data.split(' ', 1)[0]
                if module.startswith('storpool_'):
                    remaining.append(module)
            if remaining:
                rdebug('some modules were left over: {lst}'
                       .format(lst=' '.join(sorted(remaining))))
            else:
                rdebug('looks like we got rid of them all!')

            rdebug('that is all for the modules')
        except Exception as e:
            rdebug('Could not remove kernel modules: {e}'.format(e=e))

    rdebug('removing any config-related packages')
    sprepo.unrecord_packages('storpool-config')

    rdebug('let the storpool-repo layer know that we are shutting down')
    reactive.set_state('storpool-repo-add.stop')

    rdebug('goodbye, weird world!')
    reactive.set_state('l-storpool-config.stopped')
    for state in STATES_REDO['set'] + STATES_REDO['unset']:
        reactive.remove_state(state)
