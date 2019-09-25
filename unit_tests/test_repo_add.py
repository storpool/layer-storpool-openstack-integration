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

root_path = os.path.realpath(".")
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

        raise AttributeError(
            "Cannot override the MockConfig "
            '"{name}" attribute'.format(name=name)
        )


r_config = MockConfig()

spconfig.m = lambda: r_config


from spcharms.run import storpool_repo_add as testee

REPO_URL = "http://jrl:no-idea@nonexistent.storpool.example.com/"

LINES_REAL = [
    "deb http://bg.archive.ubuntu.com/ubuntu/ xenial-updates main restricted",
    "deb-src http://bg.archive.ubuntu.com/ubuntu/ "
    "xenial-updates main restricted",
]

LINES_OBSOLETE = [
    "deb https://debian.ringlet.net/storpool-juju/ xenial main",
    "deb http://repo.storpool.com/storpool-maas/ xenial main",
    "deb http://foo:bar@repo.storpool.com/storpool-maas/ xenial main",
    "deb https://foo:bar@repo.storpool.com/storpool-maas/ xenial main",
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
        self.tempdir = tempfile.TemporaryDirectory(prefix="storpool-repo-add.")

        apt_dir = "{base}/apt".format(base=self.tempdir.name)
        keyring_dir = "{base}/keyrings".format(base=self.tempdir.name)
        os.mkdir(apt_dir, mode=0o700)
        os.mkdir(keyring_dir, mode=0o700)
        self.runner = testee.RepoAddRunner(
            config_dir=apt_dir, keyring_dir=keyring_dir
        )

    def tearDown(self):
        """
        Remove the temporary directory created by the setUp() method.
        """
        super(TestStorPoolRepoAdd, self).tearDown()
        if "tempdir" in dir(self) and self.tempdir is not None:
            self.tempdir.cleanup()
            self.tempdir = None

    def fail_on_err(self, msg):
        self.fail("sputils.err() invoked: {msg}".format(msg=msg))

    def check_keydata(self):
        """
        Do some basic checks on the key data used internally to
        identify the StorPool MAAS repository key.
        """
        keydata = self.runner.key_data()
        self.assertTrue(keydata.startswith("pub:"))
        self.assertGreater(len(keydata.split(":")), 4)
        return keydata

    def check_keyfiles(self):
        """
        Do some basic checks that the final location of the StorPool
        MAAS repository signing key file is sane.
        """
        res = []
        for fname in self.runner.keyring_files:
            self.assertEqual(
                self.tempdir.name,
                os.path.commonpath([self.tempdir.name, fname]),
            )
            self.assertEqual(
                self.runner.keyring_dir,
                os.path.commonpath([self.runner.keyring_dir, fname]),
            )
            res.append(fname)
        return res

    def check_keyfiles_gpg(self, keydata, keyfiles):
        """
        Spawn a gpg child process to check that the key file actually
        contains the key identified by the key data.
        """
        checked = False
        for keyfile in keyfiles:
            if "-maas-" not in keyfile:
                continue
            checked = True
            lines = (
                subprocess.check_output(
                    [
                        "gpg",
                        "--list-keys",
                        "--batch",
                        "--with-colons",
                        "--no-default-keyring",
                        "--keyring",
                        keyfile,
                    ]
                )
                .decode()
                .split("\n")
            )
            found = [line for line in lines if line.startswith(keydata)]
            self.assertTrue(found)

        self.assertTrue(checked)

    @mock.patch("charmhelpers.core.hookenv.config", new=lambda: {})
    @mock.patch("charmhelpers.core.hookenv.charm_dir")
    def test_apt_key(self, charm_dir):
        """
        Test the routines that let APT trust the StorPool key.
        """
        charm_dir.return_value = os.getcwd()

        obsolete = os.path.join(
            self.tempdir.name, "apt", "trusted.gpg.d", "storpool-maas.key"
        )
        if not os.path.exists(os.path.dirname(obsolete)):
            os.mkdir(os.path.dirname(obsolete), mode=0o700)
        with open(obsolete, mode="w", encoding="UTF-8") as obsf:
            print("hello", file=obsf)

        keydata = self.check_keydata()
        keyfiles = self.check_keyfiles()

        for keyfile in keyfiles:
            if os.path.exists(keyfile):
                os.unlink(keyfile)
            self.assertFalse(os.path.exists(keyfile))
        self.assertTrue(os.path.isfile(obsolete))
        self.runner.install_apt_key()
        for keyfile in keyfiles:
            self.assertTrue(os.path.isfile(keyfile))
        self.assertFalse(os.path.isfile(obsolete))

        self.check_keyfiles_gpg(keydata, keyfiles)

        testee.stop(runner=self.runner)
        for keyfile in keyfiles:
            self.assertFalse(os.path.exists(keyfile))

    def check_sources_list(self):
        """
        Do some basic checks that the final location of the StorPool
        APT sources list file is sane.
        """
        res = []
        for fname in self.runner.sources_files:
            self.assertEqual(
                self.tempdir.name,
                os.path.commonpath([self.tempdir.name, fname]),
            )
            self.assertEqual(
                self.runner.config_dir,
                os.path.commonpath([self.runner.config_dir, fname]),
            )
            res.append(fname)
        return res

    def check_sources_list_contents(self, listfiles):
        """ Actually check the contents of the sources list file. """
        checked = False
        for listfile in listfiles:
            if "-maas" not in listfile:
                continue
            checked = True
            lines = open(listfile, mode="r", encoding="us-ascii").readlines()
            self.assertNotEqual(
                [],
                [
                    line
                    for line in lines
                    if line.startswith("Types:") and "deb" in line.split()
                ],
            )
            self.assertNotEqual(
                [],
                [
                    line
                    for line in lines
                    if line.startswith("Types:") and "deb-src" in line.split()
                ],
            )
            self.assertNotEqual(
                [],
                [
                    line
                    for line in lines
                    if line.startswith("URIs:") and REPO_URL in line
                ],
            )

        self.assertTrue(checked)

    @mock.patch("charmhelpers.core.hookenv.config", new=lambda: {})
    @mock.patch("charmhelpers.core.hookenv.charm_dir")
    def test_sources_list(self, charm_dir):
        """
        Test the routines that let APT look at the StorPool repository.
        """
        charm_dir.return_value = os.getcwd()
        r_config.r_set("storpool_repo_url", REPO_URL, True)

        obsolete = os.path.join(self.runner.sources_dir, "storpool-maas.list")
        if not os.path.exists(os.path.dirname(obsolete)):
            os.mkdir(os.path.dirname(obsolete), mode=0o700)
        with open(obsolete, mode="w", encoding="UTF-8") as obsf:
            print("hello", file=obsf)

        listfiles = self.check_sources_list()
        for listfile in listfiles:
            if os.path.exists(listfile):
                os.path.unlink(listfile)
            self.assertFalse(os.path.exists(listfile))

        self.assertTrue(os.path.isfile(obsolete))
        self.runner.install_apt_repo()
        self.assertFalse(os.path.isfile(obsolete))

        for listfile in listfiles:
            self.assertTrue(os.path.exists(listfile))
        self.check_sources_list_contents(listfiles)

        testee.stop(runner=self.runner)
        for listfile in listfiles:
            self.assertFalse(os.path.exists(listfile))

    def test_error(self):
        """
        Test the package install exception.
        """
        names = ["storpool-beacon", "storpool-block", "txn"]
        cause = KeyError("weirdness")
        e = sperror.StorPoolPackageInstallException(names, cause)
        self.assertIsInstance(e, sperror.StorPoolPackageInstallException)
        self.assertIsInstance(e, Exception)
        self.assertEqual(e.names, names)
        self.assertEqual(e.cause, cause)
        self.assertRegex(
            str(e), ".*storpool-beacon storpool-block txn.*:.*weirdness"
        )
