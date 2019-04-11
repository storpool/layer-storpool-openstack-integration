"""
A Juju charm layer that adds the StorPool Ubuntu package repository to
the node's APT configuration.
"""

from __future__ import print_function

import os
import platform
import re
import tempfile
import subprocess

from charmhelpers.core import hookenv

from spcharms import config as spconfig
from spcharms import error as sperror
from spcharms import status as spstatus
from spcharms import utils as sputils

APT_CONFIG_DIR = '/etc/apt'
APT_SOURCES_DIR = 'sources.list.d'
APT_SOURCES_FILE = 'storpool-maas.list'
APT_KEYRING_DIR = 'trusted.gpg.d'
APT_KEYRING_FILE = 'storpool-maas.gpg'

KNOWN_CODENAMES = ('bionic', 'xenial', 'trusty', 'precise')


def apt_sources_list():
    """
    Generate the name of the APT file to store the StorPool repo data.
    """
    return '{dir}/{subdir}/{file}'.format(dir=APT_CONFIG_DIR,
                                          subdir=APT_SOURCES_DIR,
                                          file=APT_SOURCES_FILE)


def apt_keyring():
    """
    Generate the name of the APT file to store the StorPool OpenPGP key.
    """
    return '{dir}/{subdir}/{file}'.format(dir=APT_CONFIG_DIR,
                                          subdir=APT_KEYRING_DIR,
                                          file=APT_KEYRING_FILE)


def key_data():
    """
    Hardcode the StorPool package signing key.
    """
    return 'pub:-:2048:1:7FF335CEB2E5AAA2:'


def repo_url():
    """
    Get the StorPool package repository URL from the configuration.
    """
    return spconfig.m()['storpool_repo_url']


def rdebug(s, cond=None):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix='repo-add', cond=cond)


def get_version_codename():
    dist = platform.dist()
    if dist[0].lower() == 'ubuntu':
        return dist[2]

    with open('/etc/os-release', mode='r') as f:
        lines = {}
        for line in f.readlines():
            (k, v) = line.rstrip().split('=', 1)
            lines[k] = v.strip('"\'')
        codename = lines.get('VERSION_CODENAME', lines.get('UBUNTU_CODENAME'))
        version = lines.get('VERSION', '').lower()
        if codename is None:
            for codename in KNOWN_CODENAMES:
                if codename in version:
                    return codename
            raise sperror.StorPoolException(
              'No VERSION_CODENAME or UBUNTU_CODENAME in '
              'the /etc/os-release file')
        elif re.match('[a-zA-Z0-9_]+$', codename) is None:
            raise sperror.StorPoolException(
              'Invalid codename "{codename}" in the /etc/os-release file'
              .format(codename=codename))
        return codename


def apt_file_contents(url):
    """
    Generate the text that should be put into the APT sources list.
    """
    codename = get_version_codename()
    return {
        'mandatory': 'deb {url} {name} main'.format(url=url, name=codename),
        'optional': 'deb-src {url} {name} main'.format(url=url, name=codename),
    }


def has_apt_key():
    """
    Check whether the local APT installation has the StorPool signing key.
    """
    rdebug('has_apt_key() invoked', cond='repo-add')
    current = subprocess.check_output([
                                       'apt-key',
                                       'adv',
                                       '--list-keys',
                                       '--batch',
                                       '--with-colons'
                                      ])
    kdata = key_data()
    return bool(list(filter(
        lambda s: s.startswith(kdata),
        current.decode().split('\n')
    )))


def has_apt_repo():
    """
    Check whether the local APT installation has the StorPool repository.
    """
    rdebug('has_apt_repo() invoked')
    filename = apt_sources_list()
    if not os.path.isfile(filename):
        return False

    contents = apt_file_contents(repo_url())
    with open(filename, mode='r') as f:
        found_mandatory = False
        for line in map(lambda s: s.strip(), f.readlines()):
            if line == contents['mandatory']:
                found_mandatory = True
            elif contents['optional'] not in line:
                return False
        return found_mandatory


def get_gpg_version_line(prog):
    """ Parse a GnuPG version line. """
    try:
        lines = subprocess.check_output([prog, '--version']).decode('Latin-1')
    except (subprocess.CalledProcessError, OSError) as exc:
        rdebug('Could not execute `{prog} --version`: {exc}'
               .format(prog=prog, exc=exc),
               cond='repo-add')
        return {}

    first = lines.split('\n')[0]
    rdebug('--version first line: {first}'.format(first=first),
           cond='repo-add')
    res = {'full': first}

    fields = first.split()
    rdebug('--version fields: {fields}'.format(fields=repr(fields)),
           cond='repo-add')
    if len(fields) == 3 and fields[0] == 'gpg':
        res['version'] = fields[2]
        rdebug('--version looks like GnuPG version {ver}'
               .format(ver=res['version']),
               cond='repo-add')

    return res


def is_gpg_1(prog):
    """ Figure out if a program is a GnuPG 1.x executable. """
    rdebug('Checking whether {prog} is a GnuPG 1.x executable'
           .format(prog=prog),
           cond='repo-add')
    line = get_gpg_version_line(prog)
    return line.get('version', '').startswith('1.')


def is_gpg_executable(prog):
    """ Figure out if a program is a GnuPG executable at all. """
    rdebug('Checking whether {prog} is a GnuPG executable at all'
           .format(prog=prog),
           cond='repo-add')
    return 'version' in get_gpg_version_line(prog)


def detect_gpg_program():
    """ Detect (possibly install) the GnuPG 1.x executable to use. """
    rdebug('Trying to figure out what GnuPG program to use', cond='repo-add')
    if is_gpg_1('gpg'):
        return 'gpg'
    if not is_gpg_executable('gpg1'):
        subprocess.check_call([
            'env', 'DEBIAN_FRONTENT=noninteractive',
            'apt-get', '-y', 'install', 'gnupg1',
        ])
    if is_gpg_1('gpg1'):
        return 'gpg1'
    raise Exception('Could not find a GnuPG 1.x executable')


def install_apt_key():
    """
    Add the StorPool package signing key to the local APT setup.
    """
    rdebug('install_apt_key() invoked', cond='repo-add')
    keyfile = '{charm}/templates/{fname}'.format(charm=hookenv.charm_dir(),
                                                 fname='storpool-maas.key')
    filename = apt_keyring()
    dirname = os.path.dirname(filename)
    if not os.path.isdir(dirname):
        rdebug('- creating the {dir} directory first'.format(dir=dirname),
               cond='repo-add')
        os.mkdir(dirname, 0o755)
    rdebug('about to invoke gpg import into {keyfile}'.format(keyfile=keyfile),
           cond='repo-add')
    gpg_prog = detect_gpg_program()
    rdebug('Detected GnuPG 1.x program {gpg}'.format(gpg=gpg_prog),
           cond='repo-add')
    subprocess.check_call([gpg_prog, '--no-default-keyring',
                           '--keyring', filename, '--import', keyfile])
    os.chmod(filename, 0o644)


def install_apt_repo():
    """
    Add the StorPool package repository to the local APT setup.
    """
    rdebug('install_apt_repo() invoked', cond='repo-add')

    rdebug('cleaning up the /etc/apt/sources.list file first', cond='repo-add')
    sname = '{apt}/sources.list'.format(apt=APT_CONFIG_DIR)
    with open(sname, mode='r') as f:
        with tempfile.NamedTemporaryFile(dir=APT_CONFIG_DIR,
                                         mode='w+t',
                                         delete=False) as tempf:
            removed = 0
            for line in f.readlines():
                if 'https://debian.ringlet.net/storpool-maas' in line or \
                   'https://debian.ringlet.net/storpool-juju' in line or \
                   'http://repo.storpool.com/storpool-maas' in line or \
                   '@repo.storpool.com/storpool-maas' in line:
                    removed = removed + 1
                    continue
                print(line, file=tempf, end='')

            if removed:
                rdebug('Removing {removed} lines from {sname}'
                       .format(removed=removed, sname=sname))
                tempf.flush()
                os.rename(tempf.name, sname)
            else:
                rdebug('No need to remove any lines from {sname}'
                       .format(sname=sname))
                os.unlink(tempf.name)

    contents = apt_file_contents(repo_url())
    text = '{mandatory}\n# {optional}\n'.format(**contents)
    filename = apt_sources_list()
    rdebug('creating the {fname} file'.format(fname=filename), cond='repo-add')
    rdebug('contents: {text}'.format(text=text), cond='repo-add')
    dirname = os.path.dirname(filename)
    if not os.path.isdir(dirname):
        rdebug('- creating the {dir} directory first'.format(dir=dirname),
               cond='repo-add')
        os.mkdir(dirname, mode=0o755)
    with tempfile.NamedTemporaryFile(dir=dirname,
                                     mode='w+t',
                                     prefix='.storpool-maas.',
                                     suffix='.list',
                                     delete=False) as tempf:
        print(text, file=tempf, end='', flush=True)
        os.chmod(tempf.name, 0o644)
        os.rename(tempf.name, filename)


def do_install_apt_key():
    """
    Check and, if necessary, install the StorPool package signing key.
    """
    rdebug('install-apt-key invoked')
    spstatus.npset('maintenance', 'checking for the APT key')

    if not has_apt_key():
        install_apt_key()

    rdebug('install-apt-key seems fine')
    spstatus.npset('maintenance', '')


def do_install_apt_repo():
    """
    Check and, if necessary, add the StorPool repository.
    """
    rdebug('install-apt-repo invoked')
    spstatus.npset('maintenance', 'checking for the APT repository')

    if not has_apt_repo():
        install_apt_repo()

    rdebug('install-apt-repo seems fine')
    spstatus.npset('maintenance', '')


def do_update_apt():
    """
    Invoke `apt-get update` to fetch data from the StorPool repository.
    """
    rdebug('invoking apt-get update')
    spstatus.npset('maintenance', 'updating the APT cache')

    subprocess.check_call(['apt-get', 'update'])

    rdebug('update-apt seems fine')
    spstatus.npset('maintenance', '')


STATES_REDO = {
    'set': [
    ],
    'unset': [
        'storpool-repo-add.available',
    ],
}


def try_config():
    """
    Check if the configuration has been fully set.
    """
    rdebug('reconfigure')
    spstatus.reset_if_allowed('storpool-repo-add')
    config = spconfig.m()

    repo_url = config.get('storpool_repo_url', None)
    if repo_url is None or repo_url == '':
        raise sperror.StorPoolNoConfigException(['storpool_repo_url'])
    else:
        rdebug('got a repository URL: {url}'.format(url=repo_url))


def run():
    rdebug('And now we are at the bottom of the well...')
    try_config()
    do_install_apt_key()
    do_install_apt_repo()
    do_update_apt()


def stop():
    """
    Clean up and no longer attempt to install anything.
    """
    rdebug('storpool-repo-add stopping as requested')

    for fname in (apt_sources_list(), apt_keyring()):
        if os.path.isfile(fname):
            rdebug('- trying to remove {name}'.format(name=fname),
                   cond='repo-add')
            try:
                os.unlink(fname)
            except Exception as e:
                rdebug('- could not remove {name}: {e}'
                       .format(name=fname, e=e))
        else:
            rdebug('- no {name} to remove'.format(name=fname))
