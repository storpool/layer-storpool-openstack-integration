"""
A Juju charm layer that adds the StorPool Ubuntu package repository to
the node's APT configuration.
"""

from __future__ import print_function

import base64
import os
import platform
import re
import tempfile
import subprocess

from charmhelpers.core import templating

from spcharms import config as spconfig
from spcharms import error as sperror
from spcharms import status as spstatus
from spcharms import utils as sputils

DEFAULT_APT_CONFIG_DIR = '/etc/apt'
DEFAULT_APT_SOURCES_DIR = 'sources.list.d'
DEFAULT_APT_SOURCES_FILES = ('storpool-maas.sources', 'storpool.sources')
DEFAULT_KEYRING_DIR = '/usr/share/keyrings'
DEFAULT_KEYRING_FILES = ('storpool-maas-keyring.gpg', 'storpool-keyring.gpg')

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


class RepoAddRunner:
    """ Add the StorPool repository definitions to the running system. """
    def __init__(self,
                 config_dir=None,
                 sources_dir=None,
                 sources_files=None,
                 keyring_dir=None,
                 keyring_files=None):
        """ Create a RepoAddRunner object with the specified settings. """
        self.config_dir = (
            config_dir if config_dir is not None
            else DEFAULT_APT_CONFIG_DIR
        )
        self.sources_dir = (
            sources_dir if sources_dir is not None
            else os.path.join(self.config_dir, DEFAULT_APT_SOURCES_DIR)
        )
        self.sources_files = (
            sources_files if sources_files is not None
            else [
                os.path.join(self.sources_dir, fname)
                for fname in DEFAULT_APT_SOURCES_FILES
            ]
        )
        self.keyring_dir = (
            keyring_dir if keyring_dir is not None
            else DEFAULT_KEYRING_DIR
        )
        self.keyring_files = (
            keyring_files if keyring_files is not None
            else [
                os.path.join(self.keyring_dir, fname)
                for fname in DEFAULT_KEYRING_FILES
            ]
        )
        if len(self.keyring_files) != len(self.sources_files):
            raise Exception('{tname} must be initialized with the same number '
                            'of source files and keyring files'
                            .format(tname=type(self).__name__))

    def _temp_rendered_file(self, template, destdir, context=None,
                            b64encoded=False):
        """ Write out a rendered template to a temporary file. """
        if context is None:
            context = {}

        if b64encoded:
            encoded = templating.render(
                source=template,
                target=None,
                context=context,
            )
            decoded = base64.b64decode(encoded)
            tempf = tempfile.NamedTemporaryFile(
                dir=destdir,
                prefix='.storpool.',
                suffix='.gpg',
                mode='wb',
            )
            tempf.write(decoded)
            tempf.flush()
        else:
            tempf = tempfile.NamedTemporaryFile(
                dir=destdir,
                prefix='.storpool.',
                suffix='.txt',
            )
            templating.render(
                source=template,
                target=tempf.name,
                context=context,
            )
        return tempf

    def _compare_and_install(self, template, fname,
                             context=None, b64encoded=False):
        with self._temp_rendered_file(
            template,
            os.path.dirname(fname),
            b64encoded=b64encoded,
            context=context,
        ) as tempf:
            rdebug('  - tempf {tempf} for {fname}'
                   .format(tempf=tempf.name, fname=fname),
                   cond='repo-add')
            subprocess.check_call([
                'install',
                '-C', '-o', 'root', '-g', 'root', '-m', '644',
                '--',
                tempf.name, fname,
            ])

    def key_data(self):
        """ Hardcode the StorPool package signing key. """
        return 'pub:-:2048:1:7FF335CEB2E5AAA2:'

    def repo_url(self):
        """ Get the StorPool package repository URL from the configuration. """
        return spconfig.m()['storpool_repo_url']

    def install_apt_key(self):
        """ Add the StorPool package signing key to the local APT setup. """
        rdebug('install_apt_key() invoked', cond='repo-add')
        for fname in self.keyring_files:
            template = '{base}.txt'.format(base=os.path.basename(fname))
            self._compare_and_install(template, fname, b64encoded=True)

        obs_name = os.path.join(
            self.config_dir, 'trusted.gpg.d', 'storpool-maas.key')
        if os.path.exists(obs_name):
            rdebug('removing the obsolete {name}'.format(name=obs_name),
                   cond='repo-add')
            os.unlink(obs_name)

    def install_apt_repo(self):
        """ Add the StorPool package repository to the local APT setup. """
        rdebug('install_apt_repo() invoked', cond='repo-add')

        codename = get_version_codename()
        for fname, keyfile in zip(self.sources_files, self.keyring_files):
            template = os.path.basename(fname)
            self._compare_and_install(
                template,
                fname,
                context={
                    'repo_url': self.repo_url(),
                    'codename': codename,
                    'keyring': keyfile,
                },
            )

        obs_name = os.path.join(
            self.sources_dir, 'storpool-maas.list')
        if os.path.exists(obs_name):
            rdebug('removing the obsolete {name}'.format(name=obs_name),
                   cond='repo-add')
            os.unlink(obs_name)

    def do_install_apt_key(self):
        """ Check and, if necessary, install our package signing key. """
        rdebug('install-apt-key invoked')
        spstatus.npset('maintenance', 'checking for the APT key')

        self.install_apt_key()

        rdebug('install-apt-key seems fine')
        spstatus.npset('maintenance', '')

    def do_install_apt_repo(self):
        """ Check and, if necessary, add our repository. """
        rdebug('install-apt-repo invoked')
        spstatus.npset('maintenance', 'checking for the APT repository')

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
    for fname in runner.sources_files + runner.keyring_files:
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
