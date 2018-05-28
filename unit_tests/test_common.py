#!/usr/bin/python3

"""
A set of unit tests for the storpool-common layer.
"""

import os
import sys
import unittest

import mock

root_path = os.path.realpath('lib')
if root_path not in sys.path:
    sys.path.insert(0, root_path)

lib_path = os.path.realpath('unit_tests/lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from spcharms import error as sperror
from spcharms import utils as sputils


class MockReactive(object):
    def r_clear_states(self):
        self.states = set()

    def __init__(self):
        self.r_clear_states()

    def set_state(self, name):
        self.states.add(name)

    def remove_state(self, name):
        if name in self.states:
            self.states.remove(name)

    def is_state(self, name):
        return name in self.states

    def r_get_states(self):
        return set(self.states)

    def r_set_states(self, states):
        self.states = set(states)


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

    def get(self, key, default):
        return self.override.get(key, self.config.get(key, default))

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


r_state = MockReactive()
r_config = MockConfig()


def mock_reactive_states(f):
    def inner1(inst, *args, **kwargs):
        @mock.patch('charms.reactive.set_state', new=r_state.set_state)
        @mock.patch('charms.reactive.remove_state', new=r_state.remove_state)
        @mock.patch('charms.reactive.helpers.is_state', new=r_state.is_state)
        @mock.patch('spcharms.config.m', new=lambda: r_config)
        def inner2(*args, **kwargs):
            return f(inst, *args, **kwargs)

        return inner2()

    return inner1


from reactive import storpool_common as testee

COPIED_STATE = 'storpool-common.config-written'

KERNEL_PARAMS = 'initrd=something swapaccount=1 root=something.else nofb ' \
                'vga=normal nomodeset video=vesafb:off i915.modeset=0'
COMBINED_LINE = 'MemTotal: 20000 M\nprocessor : 0\n'
CGCONFIG_BASE = '/usr/share/doc/storpool/examples/cgconfig/ubuntu1604'
OS_STAT_RESULT = os.stat('/etc/passwd')


class TestStorPoolCommon(unittest.TestCase):
    """
    Test various aspects of the storpool-common layer.
    """
    def setUp(self):
        """
        Clean up the reactive states information between tests.
        """
        super(TestStorPoolCommon, self).setUp()
        r_state.r_clear_states()
        r_config.r_clear_config()
        self.save_sputils_err = sputils.err
        sputils.err = lambda *args: self.fail_on_err(*args)

    def tearDown(self):
        """
        Restore the sputils.err function.
        """
        super(TestStorPoolCommon, self).tearDown()
        sputils.err = self.save_sputils_err

    def fail_on_err(self, msg):
        self.fail('sputils.err() invoked: {msg}'.format(msg=msg))

    @mock_reactive_states
    @mock.patch('charmhelpers.core.hookenv.config', new=lambda: {})
    @mock.patch('spcharms.utils.bypassed')
    @mock.patch('spcharms.txn.install')
    @mock.patch('spcharms.repo.record_packages')
    @mock.patch('spcharms.repo.install_packages')
    @mock.patch('spcharms.status.npset')
    @mock.patch('charmhelpers.core.templating.render')
    @mock.patch('os.path.isdir')
    @mock.patch('os.walk')
    @mock.patch('os.stat')
    @mock.patch('subprocess.check_call')
    @mock.patch('charmhelpers.core.hookenv.log')
    def test_install_package(self, h_log, check_call, os_stat, os_walk, isdir,
                             render, npset, install_packages, record_packages,
                             txn_install, bypassed):
        """
        Test that the layer attempts to install packages correctly.
        """
        count_npset = npset.call_count
        count_log = h_log.call_count
        count_install = install_packages.call_count
        count_record = record_packages.call_count
        count_call = check_call.call_count
        count_txn_install = txn_install.call_count

        files_list = [
            ('', ['etc', 'usr'], []),
            ('/etc', ['cgconfig.d'], ['machine-cgsetup.conf']),
            ('/etc/cgconfig.d', [], ['machine.slice.conf', 'something.else']),
            ('/usr', [], []),
        ]
        os_walk.return_value = list(map(lambda i: (CGCONFIG_BASE + i[0],
                                                   i[1],
                                                   i[2]),
                                        files_list))
        os_stat.return_value = OS_STAT_RESULT
        isdir.return_value = True

        # Missing kernel parameters, not bypassed, error.
        mock_file = mock.mock_open(read_data='no such parameters')
        with mock.patch('reactive.storpool_common.open', mock_file,
                        create=True):
            bypassed.return_value = False
            self.assertRaises(sperror.StorPoolException,
                              testee.install_package)
            self.assertEquals(count_npset, npset.call_count)
            self.assertEquals(count_log + 2, h_log.call_count)
            self.assertEquals(count_install, install_packages.call_count)
            self.assertEquals(count_record, record_packages.call_count)
            self.assertEquals(count_call, check_call.call_count)
            self.assertEquals(set(), r_state.r_get_states())

        # Missing kernel parameters, bypassed, no StorPool version
        mock_file = mock.mock_open(read_data='no such parameters')
        with mock.patch('reactive.storpool_common.open', mock_file,
                        create=True):
            bypassed.return_value = True
            self.assertRaises(sperror.StorPoolNoConfigException,
                              testee.install_package)
            self.assertEquals(count_npset + 1, npset.call_count)
            self.assertEquals(count_log + 5, h_log.call_count)
            self.assertEquals(count_install, install_packages.call_count)
            self.assertEquals(count_record, record_packages.call_count)
            self.assertEquals(count_call, check_call.call_count)
            self.assertEquals(set(), r_state.r_get_states())

        # Correct kernel parameters, no StorPool version
        mock_file = mock.mock_open(read_data=KERNEL_PARAMS)
        with mock.patch('reactive.storpool_common.open', mock_file,
                        create=True):
            bypassed.return_value = False
            self.assertRaises(sperror.StorPoolNoConfigException,
                              testee.install_package)
            self.assertEquals(count_npset + 2, npset.call_count)
            self.assertEquals(count_log + 7, h_log.call_count)
            self.assertEquals(count_install, install_packages.call_count)
            self.assertEquals(count_record, record_packages.call_count)
            self.assertEquals(count_call, check_call.call_count)
            self.assertEquals(set(), r_state.r_get_states())

        # OK, but since it seems that mock_open() is a bit limited WRT
        # opening several files in a row, let's bypass the checks and
        # just hand the /proc/meminfo contents to everyone...
        bypassed.return_value = True

        # Fail to intall the packages
        r_config.r_set('storpool_version', '16.02', False)
        mock_file = mock.mock_open(read_data=COMBINED_LINE)
        with mock.patch('reactive.storpool_common.open', mock_file,
                        create=True):
            install_packages.return_value = ('oops', [])
            self.assertRaises(sperror.StorPoolPackageInstallException,
                              testee.install_package)
            self.assertEquals(count_npset + 4, npset.call_count)
            self.assertEquals(count_log + 10, h_log.call_count)
            self.assertEquals(count_install + 1, install_packages.call_count)
            self.assertEquals(count_record, record_packages.call_count)
            self.assertEquals(count_call, check_call.call_count)
            self.assertEquals(set(), r_state.r_get_states())

        class WeirdError(BaseException):
            pass

        def raise_notimp(self, *args, **kwargs):
            """
            Simulate a child process error, strangely.
            """
            raise WeirdError('Because we said so!')

        # Installed the package correctly, `depmod -a` failed.
        install_packages.return_value = (None, ['storpool-beacon'])
        mock_file = mock.mock_open(read_data=COMBINED_LINE)
        with mock.patch('reactive.storpool_common.open', mock_file,
                        create=True):
            check_call.side_effect = raise_notimp
            self.assertRaises(WeirdError, testee.install_package)
            self.assertEquals(count_npset + 7, npset.call_count)
            self.assertEquals(count_log + 15, h_log.call_count)
            self.assertEquals(count_install + 2,
                              install_packages.call_count)
            self.assertEquals(count_record + 1,
                              record_packages.call_count)
            self.assertEquals(count_call + 1, check_call.call_count)
            self.assertEquals(set(), r_state.r_get_states())

        # Right, we may not be running on a StorPool host at all,
        # so make sure that we know whether install_package() will
        # warn about missing kernel parameters...
        warn_count = 0
        try:
            lines = open('/proc/cmdline', mode='r').readlines()
            line = lines[0]
            words = line.split()
            for param in testee.KERNEL_REQUIRED_PARAMS:
                if param not in words:
                    warn_count = 1
                    break
        except Exception:
            pass

        # Go on then...
        check_call.side_effect = None
        mock_file = mock.mock_open(read_data=COMBINED_LINE)
        with mock.patch('reactive.storpool_common.open', mock_file,
                        create=True):
            testee.install_package()
            self.assertEquals(count_npset + 11, npset.call_count)
            self.assertEquals(count_log + 33, h_log.call_count)
            self.assertEquals(count_install + 3,
                              install_packages.call_count)
            self.assertEquals(count_record + 2,
                              record_packages.call_count)
            self.assertEquals(count_call + 2 + warn_count,
                              check_call.call_count)
            self.assertEquals(count_txn_install + 3, txn_install.call_count)
            self.assertEquals(set(), r_state.r_get_states())

    @mock_reactive_states
    @mock.patch('charmhelpers.core.hookenv.config', new=lambda: r_config)
    @mock.patch('spcharms.status.npset')
    @mock.patch('spcharms.txn.install')
    @mock.patch('charmhelpers.core.host.service_restart')
    def test_copy_config_files(self, service_restart, txn_install, npset):
        """
        Test that the layer enables the system startup service.
        """
        count_txn_install = txn_install.call_count

        r_config.r_set('storpool_version', '18.01.0.deadbeef', changed=False)
        testee.copy_config_files()
        self.assertEqual(count_txn_install + 2, txn_install.call_count)
        service_restart.assert_called_once_with('rsyslog')
        self.assertEquals(set([COPIED_STATE]), r_state.r_get_states())
