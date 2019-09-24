#!/usr/bin/python3

"""
A set of unit tests for the storpool-repo-add layer.
"""

import os
import sys
import subprocess
import tempfile
import unittest

import mock

root_path = os.path.realpath('.')
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from spcharms import config as spconfig
from spcharms import error as sperror
from spcharms import utils as sputils


class SingletonSentinel(object):
    pass


SINGLETON_SENTINEL = SingletonSentinel()


initializing_config = None


class MockConfig(object):
    def r_clear_config(self):
        global initializing_config
        saved = initializing_config
        initializing_config = self
        self.override = {}
        self.changed_attrs = {}
        self.config = {}
        initializing_config = saved

    def __init__(self):
        self.r_clear_config()

    def r_set(self, key, value, changed):
        self.override[key] = value
        self.changed_attrs[key] = changed

    def get(self, key, default=SINGLETON_SENTINEL):
        if key in self.override:
            return self.override[key]
        elif default is SINGLETON_SENTINEL:
            return self.config.get(key)
        else:
            return self.config.get(key, default)

    def changed(self, key):
        return self.changed_attrs.get(key, False)

    def __getitem__(self, name):
        # Make sure a KeyError is actually thrown if needed.
        if name in self.override:
            return self.override[name]
        else:
            return self.config[name]

    def __getattr__(self, name):
        return self.config.__getattribute__(name)

    def __setattr__(self, name, value):
        if initializing_config == self:
            return super(MockConfig, self).__setattr__(name, value)

        raise AttributeError('Cannot override the MockConfig '
                             '"{name}" attribute'.format(name=name))


r_config = MockConfig()

spconfig.m = lambda: r_config


from spcharms.run import storpool_repo_add as testee

REPO_URL = 'http://jrl:no-idea@nonexistent.storpool.example.com/'

LINES_REAL = [
    'deb http://bg.archive.ubuntu.com/ubuntu/ xenial-updates main restricted',
    'deb-src http://bg.archive.ubuntu.com/ubuntu/ '
    'xenial-updates main restricted',
]

LINES_OBSOLETE = [
    'deb https://debian.ringlet.net/storpool-juju/ xenial main',
    'deb http://repo.storpool.com/storpool-maas/ xenial main',
    'deb http://foo:bar@repo.storpool.com/storpool-maas/ xenial main',
    'deb https://foo:bar@repo.storpool.com/storpool-maas/ xenial main',
]


class TestStorPoolRepoAdd(unittest.TestCase):
    """
    Test various aspects of the storpool-repo-add layer.
    """
    def setUp(self):
        """
        Clean up the reactive states information between tests.
        """
        super(TestStorPoolRepoAdd, self).setUp()
        r_config.r_clear_config()
        sputils.err.side_effect = lambda *args: self.fail_on_err(*args)
        self.tempdir = tempfile.TemporaryDirectory(prefix='storpool-repo-add.')
        self.runner = testee.RepoAddRunner(config_dir=self.tempdir.name)

    def tearDown(self):
        """
        Remove the temporary directory created by the setUp() method.
        """
        super(TestStorPoolRepoAdd, self).tearDown()
        if 'tempdir' in dir(self) and self.tempdir is not None:
            self.tempdir.cleanup()
            self.tempdir = None

    def fail_on_err(self, msg):
        self.fail('sputils.err() invoked: {msg}'.format(msg=msg))

    def check_keydata(self):
        """
        Do some basic checks on the key data used internally to
        identify the StorPool MAAS repository key.
        """
        keydata = self.runner.key_data()
        self.assertTrue(keydata.startswith('pub:'))
        self.assertGreater(len(keydata.split(':')), 4)
        return keydata

    def check_keyfile(self):
        """
        Do some basic checks that the final location of the StorPool
        MAAS repository signing key file is sane.
        """
        fname = self.runner.apt_keyring()
        self.assertEqual(self.tempdir.name,
                         os.path.commonpath([self.tempdir.name, fname]))
        self.assertEqual(self.runner.config_dir,
                         os.path.commonpath([self.runner.config_dir, fname]))
        return fname

    def check_keyfile_gpg(self, keydata, keyfile):
        """
        Spawn a gpg child process to check that the key file actually
        contains the key identified by the key data.
        """
        lines = subprocess.check_output([
            'gpg', '--list-keys', '--batch', '--with-colons',
            '--no-default-keyring', '--keyring', keyfile
        ]).decode().split('\n')
        found = filter(lambda s: s.startswith(keydata), lines)
        self.assertTrue(found)

    @mock.patch('charmhelpers.core.hookenv.config', new=lambda: {})
    @mock.patch('charmhelpers.core.hookenv.charm_dir')
    def test_apt_key(self, charm_dir):
        """
        Test the routines that let APT trust the StorPool key.
        """
        charm_dir.return_value = os.getcwd()

        keydata = self.check_keydata()
        keyfile = self.check_keyfile()

        if os.path.exists(keyfile):
            os.path.unlink(keyfile)
        self.assertFalse(os.path.exists(keyfile))
        self.runner.install_apt_key()
        self.assertTrue(os.path.isfile(keyfile))

        self.check_keyfile_gpg(keydata, keyfile)

        testee.stop(runner=self.runner)
        self.assertFalse(os.path.exists(keyfile))

    def prepare_global_sources_list(self, fname):
        """
        Prepare a file similar to /etc/apt/sources.list that contains
        "old" StorPool repo entries that should be removed.
        """
        with open(fname, mode='w') as f:
            print('\n'.join(LINES_OBSOLETE[:2]), file=f)
            print('\n'.join(LINES_REAL), file=f)
            print('\n'.join(LINES_OBSOLETE[2:]), file=f)

    def check_global_sources_list(self, fname):
        with open(fname, mode='r') as f:
            lines = f.readlines()
        self.assertEqual(lines, [line + '\n' for line in LINES_REAL])

    def check_sources_list(self):
        """
        Do some basic checks that the final location of the StorPool
        APT sources list file is sane.
        """
        fname = self.runner.apt_sources_list()
        self.assertEqual(self.tempdir.name,
                         os.path.commonpath([self.tempdir.name, fname]))
        self.assertEqual(self.runner.config_dir,
                         os.path.commonpath([self.runner.config_dir, fname]))
        return fname

    def check_sources_list_contents(self, listfile):
        """
        Actually check the contents of the sources list file.
        """
        with open(listfile, mode='r') as listf:
            first_line = listf.readline()
            self.assertIsNotNone(first_line)
            self.assertTrue(first_line.startswith('deb ' + REPO_URL + ' '))
            second_line = listf.readline()
            self.assertIsNotNone(second_line)
            self.assertTrue(second_line
                            .startswith('# deb-src ' + REPO_URL + ' '))

    def uncomment_deb_src(self, listfile):
        """
        Edit the sources list file to uncomment the deb-src line.
        """
        dirname = os.path.dirname(listfile)
        with open(listfile, mode='r') as f:
            with tempfile.NamedTemporaryFile(dir=dirname,
                                             prefix='.storpool.',
                                             suffix='.list',
                                             mode='w+t',
                                             delete=False) as tempf:
                first_line = f.readline()
                print(first_line, file=tempf, end='')

                second_line = f.readline()
                modify = second_line.startswith('# deb-src')
                if modify:
                    second_line = second_line[2:]
                print(second_line, file=tempf, end='')

                while True:
                    line = f.readline()
                    if line is None or line == '':
                        break
                    print(line, file=tempf, end='')

                tempf.flush()
                os.rename(tempf.name, listfile)
                return modify

    @mock.patch('charmhelpers.core.hookenv.config', new=lambda: {})
    def test_sources_list(self):
        """
        Test the routines that let APT look at the StorPool repository.
        """
        r_config.r_set('storpool_repo_url', REPO_URL, True)

        global_list = '{apt}/sources.list'.format(apt=self.runner.config_dir)
        if os.path.exists(global_list):
            os.path.unlink(global_list)
        self.assertFalse(os.path.exists(global_list))
        self.prepare_global_sources_list(global_list)
        self.assertTrue(os.path.isfile(global_list))

        listfile = self.check_sources_list()
        if os.path.exists(listfile):
            os.path.unlink(listfile)
        self.assertFalse(os.path.exists(listfile))

        self.assertFalse(self.runner.has_apt_repo())
        self.runner.install_apt_repo()
        self.assertTrue(self.runner.has_apt_repo())

        self.assertTrue(os.path.isfile(global_list))
        self.check_global_sources_list(global_list)

        self.assertTrue(os.path.exists(listfile))
        self.check_sources_list_contents(listfile)

        self.assertTrue(self.uncomment_deb_src(listfile))
        self.assertTrue(self.runner.has_apt_repo())

        testee.stop(runner=self.runner)
        self.assertFalse(os.path.exists(listfile))
        self.assertFalse(self.runner.has_apt_repo())

    def test_error(self):
        """
        Test the package install exception.
        """
        names = ['storpool-beacon', 'storpool-block', 'txn']
        cause = KeyError('weirdness')
        e = sperror.StorPoolPackageInstallException(names, cause)
        self.assertIsInstance(e, sperror.StorPoolPackageInstallException)
        self.assertIsInstance(e, Exception)
        self.assertEqual(e.names, names)
        self.assertEqual(e.cause, cause)
        self.assertRegex(str(e),
                         '.*storpool-beacon storpool-block txn.*:.*weirdness')
