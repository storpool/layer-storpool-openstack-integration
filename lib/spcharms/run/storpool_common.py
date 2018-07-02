"""
A Juju charm layer that installs the base StorPool packages.
"""
from __future__ import print_function

import os
import re
import subprocess
import tempfile

from charmhelpers.core import hookenv, host, templating

from spcharms import config as spconfig
from spcharms import error as sperror
from spcharms import repo as sprepo
from spcharms import status as spstatus
from spcharms import txn
from spcharms import utils as sputils

from spcharms.run import storpool_config as run_config


KERNEL_REQUIRED_PARAMS = (
    'swapaccount=1',
    'vga=normal',
    'nofb',
    'nomodeset',
    'video=vesafb:off',
    'i915.modeset=0',
)


def rdebug(s, cond=None):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix='common', cond=cond)


def install_package():
    """
    Install the base StorPool packages.
    May raise a StorPoolNoConfigException, a StorPoolPackageInstallException,
    or a generic StorPoolException.
    """
    rdebug('the common repo has become available and '
           'we do have the configuration')

    spe = sperror.StorPoolException
    rdebug('checking the kernel command line')
    with open('/proc/cmdline', mode='r') as f:
        ln = f.readline()
        if not ln:
            raise spe('Could not read a single line from /proc/cmdline')
        words = ln.split()

        # OK, so this is a bit naive, but it will do the job
        global KERNEL_REQUIRED_PARAMS
        missing = list(filter(lambda param: param not in words,
                              KERNEL_REQUIRED_PARAMS))
        if missing:
            if sputils.bypassed('kernel_parameters'):
                hookenv.log('The "kernel_parameters" bypass is meant FOR '
                            'DEVELOPMENT ONLY!  DO NOT run a StorPool cluster '
                            'in production with it!', hookenv.WARNING)
            else:
                raise spe('Missing kernel parameters: {missing}'
                          .format(missing=' '.join(missing)))

    spstatus.npset('maintenance', 'obtaining the requested StorPool version')
    spver = spconfig.m().get('storpool_version', None)
    if spver is None or spver == '':
        raise sperror.StorPoolNoConfigException(['storpool_version'])
    spmajmin = '.'.join(spver.split('.')[0:2])

    packages = {
        'storpool-cli-' + spmajmin: '*',
        'storpool-common-' + spmajmin: '*',
        'storpool-etcfiles-' + spmajmin: '*',
        'storpool-update-' + spmajmin: '*',
        'kmod-storpool-' + spmajmin + '-' + os.uname().release: '*',
        'python-storpool-' + spmajmin: '*',
    }
    if not sputils.check_in_lxc():
        packages['systemd-container'] = '*'

    spstatus.npset('maintenance', 'querying the installed StorPool packages')
    for pattern in ('storpool-*', 'kmod-storpool-*', 'python-storpool-*'):
        try:
            rdebug('obtaining information about the {pat} packages'
                   .format(pat=pattern),
                   cond='run-common')
            raw = subprocess.check_output([
                'dpkg-query', '-W', '--showformat', '${Package}\t${Status}\n',
                pattern])
            lines = raw.decode().split('\n')
            rdebug('got {count} raw lines'.format(count=len(lines)),
                   cond='run-common')

            for line in lines:
                if line == '':
                    continue
                fields = line.split('\t')
                if len(fields) != 2:
                    rdebug('- weird line with {count} fields: {line}'
                           .format(count=len(fields), line=line))
                    continue
                (pkg, status) = fields
                rdebug('- package {pkg} status {st}'
                       .format(pkg=pkg, st=status),
                       cond='run-common')
                if status == 'install ok installed' and pkg not in packages:
                    rdebug('  - adding it', cond='run-common')
                    packages[pkg] = '*'
        except Exception as e:
            rdebug('could not query the {pat} packages: {e}'
                   .format(pat=pattern, e=e))

    rdebug('{count} packages to install/upgrade'
           .format(count=len(packages.keys())))

    spstatus.npset('maintenance', 'installing the StorPool common packages')
    newly_installed = sprepo.install_packages(packages)
    if newly_installed:
        rdebug('it seems we managed to install some packages: {names}'
               .format(names=newly_installed))
        sprepo.record_packages('storpool-common', newly_installed)

        rdebug('reloading the systemd database (errors ignored)')
        subprocess.call(['systemctl', 'daemon-reload'])
        rdebug('reloading the StorPool kernel modules (errors ignored)')
        subprocess.call(['/usr/lib/storpool/update_rdma', '--yes'])
    else:
        rdebug('it seems that all the packages were installed already')

    rdebug('updating the kernel module dependencies')
    spstatus.npset('maintenance', 'updating the kernel module dependencies')
    subprocess.check_call(['depmod', '-a'])

    if not sputils.check_in_lxc():
        configure_cgroups()


def parse_cgroup_slice_size():
    vs = spconfig.m().get('cgroup_slice_size', None)
    if vs is None or vs == '':
        raise sperror.StorPoolNoConfigException(['cgroup_slice_size'])
    d = dict(map(lambda s: s.split(':'), vs.split()))
    exp = ['kernel', 'storpool', 'system', 'user']
    ks = sorted(d.keys())
    if ks != exp:
        raise sperror.StorPoolException(
            'Invalid cgroup_slice_size keys: must have exactly {exp}'
            .format(exp=exp))

    res = {}
    for k in ks:
        try:
            v = int(d[k])
            bad = False
        except ValueError:
            bad = True
        if bad or v < 0:
            raise sperror.StorPoolException(
                'Invalid cgroup_slice_size value for {k}'.format(k=k))
        res['mem_' + k] = v * 1024

    return res


def configure_cgroups():
    """
    Create the /etc/cgconfig.d/*.slice control group configuration.
    """
    spe = sperror.StorPoolException
    rdebug('gathering swap usage information for the cgroup configuration')
    re_number = re.compile('(?: 0 | [1-9][0-9]* )$', re.X)
    total_swap = 0
    with open('/proc/swaps', mode='r') as f:
        for line in f.readlines():
            fields = line.split()
            if len(fields) < 4:
                continue
            total = fields[2]
            used = fields[3]
            if not (re_number.match(total) and re_number.match(used)):
                continue
            rdebug('- {}'.format(total), cond='run-common')
            total_swap += int(total)
    total_swap = int(total_swap / 1024)
    rdebug('- total: {} MB of swap'.format(total_swap))

    rdebug('gathering CPU information for the cgroup configuration')
    with open('/proc/cpuinfo', mode='r') as f:
        lns = f.readlines()
        all_cpus = sorted(map(lambda lst: int(lst[2]),
                              filter(lambda lst: lst and lst[0] == 'processor',
                                     map(lambda s: s.split(), lns))))
    if sputils.bypassed('very_few_cpus'):
        hookenv.log('The "very_few_cpus" bypass is meant '
                    'FOR DEVELOPMENT ONLY!  DO NOT run a StorPool cluster in '
                    'production with it!', hookenv.WARNING)
        last_cpu = all_cpus[-1]
        all_cpus.extend([last_cpu, last_cpu, last_cpu])
    if len(all_cpus) < 4:
        raise spe('Not enough CPUs, need at least 4')
    tdata = {
        'cpu_rdma': str(all_cpus[0]),
        'cpu_beacon': str(all_cpus[1]),
        'cpu_block': str(all_cpus[2]),
        'cpu_rest': '{min}-{max}'.format(min=all_cpus[3], max=all_cpus[-1]),
    }

    rdebug('gathering system memory information for the cgroup configuration')
    with open('/proc/meminfo', mode='r') as f:
        while True:
            line = f.readline()
            if not line:
                raise spe('Could not find MemTotal in /proc/meminfo')
            words = line.split()
            if words[0] == 'MemTotal:':
                mem_total = int(words[1])
                unit = words[2].upper()
                if unit.startswith('K'):
                    mem_total = int(mem_total / 1024)
                elif unit.startswith('M'):
                    pass
                elif unit.startswith('G'):
                    mem_total = mem_total * 1024
                else:
                    raise spe('Could not parse the "{u}" unit for MemTotal ' +
                              'in /proc/meminfo'.format(u=words[2]))
                break
    mem = parse_cgroup_slice_size()
    if sputils.bypassed('very_little_memory'):
        hookenv.log('The "very_little_memory" bypass is meant '
                    'FOR DEVELOPMENT ONLY!  DO NOT run a StorPool cluster in '
                    'production with it!', hookenv.WARNING)
        mem['mem_system'] = 1 * 1900
        mem['mem_user'] = 1 * 512
        mem['mem_storpool'] = 1 * 1024
        mem['mem_kernel'] = 1 * 512
    mem_reserved = mem['mem_system'] + mem['mem_user'] + mem['mem_storpool'] \
        + mem['mem_kernel']
    if mem_total <= mem_reserved:
        raise spe('Not enough memory, only have {total}M, need {mem}M'
                  .format(mem=mem_reserved, total=mem_total))
    mem['mem_machine'] = mem_total - mem_reserved

    mem['memsw_system'] = mem['mem_system'] + total_swap
    mem['memsw_user'] = mem['mem_user'] + total_swap
    mem['memsw_machine'] = mem['mem_machine'] + total_swap

    tdata.update(mem)

    rdebug('generating the cgroup configuration: {tdata}'.format(tdata=tdata))
    if not os.path.isdir('/etc/cgconfig.d'):
        os.mkdir('/etc/cgconfig.d', mode=0o755)
    cgconfig_dir = '/usr/share/doc/storpool/examples/cgconfig/ubuntu1604'
    for (path, _, files) in os.walk(cgconfig_dir):
        for fname in files:
            src = path + '/' + fname
            dst = src.replace(cgconfig_dir, '')
            dstdir = os.path.dirname(dst)
            if not os.path.isdir(dstdir):
                os.makedirs(dstdir, mode=0o755)

            if fname in (
                         'machine.slice.conf',
                         'storpool.slice.conf',
                         'system.slice.conf',
                         'user.slice.conf',
                         'machine-cgsetup.conf',
                        ):
                with tempfile.NamedTemporaryFile(dir='/tmp',
                                                 mode='w+t',
                                                 delete=True) as tempf:
                    rdebug('- generating {tempf} for {dst}'
                           .format(dst=dst, tempf=tempf.name),
                           cond='run-common')
                    templating.render(
                                      source=fname,
                                      target=tempf.name,
                                      owner='root',
                                      perms=0o644,
                                      context=tdata,
                                     )
                    rdebug('- generating {dst}'.format(dst=dst))
                    txn.install('-o', 'root', '-g', 'root', '-m', '644', '--',
                                tempf.name, dst)
            elif fname == 'storpool_cgmove_cron':
                if os.path.isfile(dst):
                    rdebug('- removing stale file {dst}'.format(dst=dst))
                    try:
                        os.unlink(dst)
                    except Exception as e:
                        rdebug('COULD NOT remove {dst}: {e}'
                               .format(dst=dst, e=e))
                else:
                    rdebug('- not installing stale {src}'.format(src=src))
            else:
                mode = '{:o}'.format(os.stat(src).st_mode & 0o777)
                rdebug('- installing {src} as {dst}'.format(src=src, dst=dst))
                txn.install('-o', 'root', '-g', 'root', '-m', mode, '--',
                            src, dst)

    rdebug('starting the cgconfig service')
    rdebug('- refreshing the systemctl service database')
    subprocess.check_call(['systemctl', 'daemon-reload'])
    rdebug('- starting the cgconfig service')
    try:
        host.service_resume('cgconfig')
    except Exception:
        pass

    spstatus.npset('maintenance', '')


def copy_config_files():
    """
    Install some configuration files.
    """
    spstatus.npset('maintenance', 'copying the storpool-common config files')
    spver = spconfig.m().get('storpool_version', None)
    spmajmin = '.'.join(spver.split('.')[0:2])
    basedir = '/usr/lib/storpool/etcfiles/storpool-common-' + spmajmin
    for f in (
        '/etc/rsyslog.d/99-StorPool.conf',
        '/etc/sysctl.d/99-StorPool.conf',
    ):
        rdebug('installing {fname}'.format(fname=f))
        txn.install('-o', 'root', '-g', 'root', '-m', '644', basedir + f, f)

    rdebug('about to restart rsyslog')
    spstatus.npset('maintenance', 'restarting the system logging service')
    host.service_restart('rsyslog')

    spstatus.npset('maintenance', '')


def run():
    rdebug('Run, config, run!')
    run_config.run()
    rdebug('Returning to the storpool-common setup')
    install_package()
    copy_config_files()


def stop():
    """
    Clean up, remove the config files, uninstall the packages.
    """
    rdebug('storpool-common.stop invoked')

    rdebug('removing any base StorPool packages')
    sprepo.unrecord_packages('storpool-common')

    rdebug('letting storpool-config know')
    run_config.stop()
