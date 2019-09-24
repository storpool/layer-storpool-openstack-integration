"""
A Juju charm layer that adds the StorPool Ubuntu package repository to
the node's APT configuration.
"""

from __future__ import print_function

import datetime
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

DEFAULT_APT_CONFIG_DIR = '/etc/apt'
DEFAULT_APT_SOURCES_DIR = 'sources.list.d'
DEFAULT_APT_SOURCES_FILE = 'storpool-maas.list'
DEFAULT_APT_KEYRING_DIR = 'trusted.gpg.d'
DEFAULT_APT_KEYRING_FILE = 'storpool-maas.gpg'

KNOWN_CODENAMES = ('bionic', 'xenial', 'trusty', 'precise')


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


class RepoAddRunner:
    """ Add the StorPool repository definitions to the running system. """
    def __init__(self,
                 config_dir=DEFAULT_APT_CONFIG_DIR,
                 sources_dir=DEFAULT_APT_SOURCES_DIR,
                 sources_file=DEFAULT_APT_SOURCES_FILE,
                 keyring_dir=DEFAULT_APT_KEYRING_DIR,
                 keyring_file=DEFAULT_APT_KEYRING_FILE):
        """ Create a RepoAddRunner object with the specified settings. """
        self.config_dir = config_dir
        self.sources_dir = sources_dir
        self.sources_file = sources_file
        self.keyring_dir = keyring_dir
        self.keyring_file = keyring_file

    def apt_sources_list(self):
        """ Get the name of the APT file to store the StorPool repo data. """
        return '{dir}/{subdir}/{file}'.format(dir=self.config_dir,
                                              subdir=self.sources_dir,
                                              file=self.sources_file)

    def apt_keyring(self):
        """ Get the name of the APT file to store the StorPool OpenPGP key. """
        return '{dir}/{subdir}/{file}'.format(dir=self.config_dir,
                                              subdir=self.keyring_dir,
                                              file=self.keyring_file)

    def key_data(self):
        """ Hardcode the StorPool package signing key. """
        return 'pub:-:2048:1:7FF335CEB2E5AAA2:'

    def repo_url(self):
        """ Get the StorPool package repository URL from the configuration. """
        return spconfig.m()['storpool_repo_url']

    def apt_file_contents(self, url):
        """ Get the text that should be put into the APT sources list. """
        codename = get_version_codename()
        return {
            'mandatory': 'deb {url} {name} main'.format(
                url=url, name=codename),
            'optional': 'deb-src {url} {name} main'.format(
                url=url, name=codename),
        }

    def has_apt_key(self):
        """ Check whether the local APT installation has our signing key. """
        rdebug('has_apt_key() invoked', cond='repo-add')
        current = subprocess.check_output([
                                           'apt-key',
                                           'adv',
                                           '--list-keys',
                                           '--batch',
                                           '--with-colons'
                                          ])
        kdata = self.key_data()
        rdebug('- got key data {kdata} and output {output}'
               .format(kdata=repr(kdata), output=repr(current)))
        for line in current.decode().split('\n'):
            rdebug('- line {line}'.format(line=repr(line)))
            if not line.startswith(kdata):
                continue
            rdebug('  - ours?')
            fields = line.split(':')
            rdebug('  - checking {flds}'.format(flds=repr(fields)))
            expiry = fields[6]
            exp_fields = expiry.split('-')
            rdebug('  - and {flds}'.format(flds=repr(exp_fields)))

            try:
                if len(exp_fields) == 1:
                    exp_time = datetime.datetime.fromtimestamp(
                        int(exp_fields[0]))
                elif len(exp_fields) == 3:
                    exp_time = datetime.datetime(
                        year=int(exp_fields[0]),
                        month=int(exp_fields[1]),
                        day=int(exp_fields[2]),
                    )
            except Exception as err:
                rdebug('- could not parse {line}: {etype}: {err}'
                       .format(line=repr(line),
                               etype=type(err).__name__,
                               err=repr(err)))
                continue
            rdebug('  - exp_time {exp}'.format(exp=exp_time))

            if exp_time > datetime.datetime.now():
                rdebug('  - found one!')
                return True
            rdebug('  - nah...')

        rdebug('- nothing found')
        return False

    def has_apt_repo(self):
        """ Check whether the local APT installation has our repository. """
        rdebug('has_apt_repo() invoked')
        filename = self.apt_sources_list()
        if not os.path.isfile(filename):
            return False

        contents = self.apt_file_contents(self.repo_url())
        with open(filename, mode='r') as f:
            found_mandatory = False
            for line in map(lambda s: s.strip(), f.readlines()):
                if line == contents['mandatory']:
                    found_mandatory = True
                elif contents['optional'] not in line:
                    return False
            return found_mandatory

    def install_apt_key(self):
        """ Add the StorPool package signing key to the local APT setup. """
        rdebug('install_apt_key() invoked', cond='repo-add')
        keyfile = '{charm}/templates/{fname}'.format(charm=hookenv.charm_dir(),
                                                     fname='storpool-maas.key')
        filename = self.apt_keyring()
        dirname = os.path.dirname(filename)
        if not os.path.isdir(dirname):
            rdebug('- creating the {dir} directory first'.format(dir=dirname),
                   cond='repo-add')
            os.mkdir(dirname, 0o755)
        rdebug('about to invoke gpg import into {keyfile}'
               .format(keyfile=keyfile),
               cond='repo-add')
        gpg_prog = detect_gpg_program()
        rdebug('Detected GnuPG 1.x program {gpg}'.format(gpg=gpg_prog),
               cond='repo-add')
        with tempfile.TemporaryDirectory() as tempd:
            subprocess.check_call([
                'env', 'GNUPGHOME={tempd}'.format(tempd=tempd),
                gpg_prog, '--no-default-keyring', '--keyring', filename,
                '--import', keyfile
            ])
        os.chmod(filename, 0o644)

    def install_apt_repo(self):
        """ Add the StorPool package repository to the local APT setup. """
        rdebug('install_apt_repo() invoked', cond='repo-add')

        rdebug('cleaning up the /etc/apt/sources.list file first',
               cond='repo-add')
        sname = '{apt}/sources.list'.format(apt=self.config_dir)
        with open(sname, mode='r') as f:
            with tempfile.NamedTemporaryFile(dir=self.config_dir,
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

        contents = self.apt_file_contents(self.repo_url())
        text = '{mandatory}\n# {optional}\n'.format(**contents)
        filename = self.apt_sources_list()
        rdebug('creating the {fname} file'.format(fname=filename),
               cond='repo-add')
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

    def do_install_apt_key(self):
        """ Check and, if necessary, install our package signing key. """
        rdebug('install-apt-key invoked')
        spstatus.npset('maintenance', 'checking for the APT key')

        if not self.has_apt_key():
            self.install_apt_key()

        rdebug('install-apt-key seems fine')
        spstatus.npset('maintenance', '')

    def do_install_apt_repo(self):
        """ Check and, if necessary, add our repository. """
        rdebug('install-apt-repo invoked')
        spstatus.npset('maintenance', 'checking for the APT repository')

        if not self.has_apt_repo():
            self.install_apt_repo()

        rdebug('install-apt-repo seems fine')
        spstatus.npset('maintenance', '')

    def do_update_apt(self):
        """ Invoke `apt-get update` to fetch data from our repository. """
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
    """ Check if the configuration has been fully set. """
    rdebug('reconfigure')
    spstatus.reset_if_allowed('storpool-repo-add')
    config = spconfig.m()

    repo_url = config.get('storpool_repo_url', None)
    if repo_url is None or repo_url == '':
        raise sperror.StorPoolNoConfigException(['storpool_repo_url'])
    else:
        rdebug('got a repository URL: {url}'.format(url=repo_url))


def run(runner=None):
    """ Set up the StorPool repository if all the configuration is present. """
    rdebug('And now we are at the bottom of the well...')
    if runner is None:
        runner = RepoAddRunner()
    try_config()
    runner.do_install_apt_key()
    runner.do_install_apt_repo()
    runner.do_update_apt()


def stop(runner=None):
    """ Clean up and no longer attempt to install anything. """
    rdebug('storpool-repo-add stopping as requested')

    if runner is None:
        runner = RepoAddRunner()
    for fname in (runner.apt_sources_list(), runner.apt_keyring()):
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
