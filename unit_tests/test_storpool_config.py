#!/usr/bin/python3

"""
A set of unit tests for the storpool-config layer.
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
        self.config = {}
        initializing_config = saved

    def __init__(self):
        self.r_clear_config()

    def r_set(self, key, value):
        self.override[key] = value

    def get(self, key, default):
        return self.override.get(key, self.config.get(key, default))

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


from reactive import storpool_config as testee


class TestStorPoolConfig(unittest.TestCase):
    """
    Test various aspects of the storpool-config layer.
    """
    def setUp(self):
        """
        Clean up the reactive states information between tests.
        """
        super(TestStorPoolConfig, self).setUp()
        r_state.r_clear_states()
        r_config.r_clear_config()
        self.save_sputils_err = sputils.err
        sputils.err = lambda *args: self.fail_on_err(*args)

    def tearDown(self):
        """
        Restore the sputils.err function.
        """
        super(TestStorPoolConfig, self).tearDown()
        sputils.err = self.save_sputils_err

    def fail_on_err(self, msg):
        self.fail('sputils.err() invoked: {msg}'.format(msg=msg))

    @mock_reactive_states
    @mock.patch('charmhelpers.core.hookenv.config', new=lambda: None)
    @mock.patch('spcharms.status.npset')
    @mock.patch('spcharms.config.unset_our_id')
    def test_check_config(self, unset_our_id, npset):
        """
        Test that the config-changed hook properly detects the presence of
        the storpool_conf setting.
        """
        states = {
            'none': set([
            ]),

            'all': set([
                'l-storpool-config.config-network',
            ]),

            'got-config': set([
            ]),
        }
        count_npset = npset.call_count
        count_unset = unset_our_id.call_count

        # No configuration at all
        r_state.r_set_states(states['none'])
        self.kv_unset_call_count = 0
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)
        self.assertEquals(states['none'], r_state.r_get_states())
        self.assertEquals(count_npset, npset.call_count)
        self.assertEquals(count_unset + 1, unset_our_id.call_count)

        r_state.r_set_states(states['all'])
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)
        self.assertEquals(states['none'], r_state.r_get_states())
        self.assertEquals(count_npset, npset.call_count)
        self.assertEquals(count_unset + 2, unset_our_id.call_count)

        # An empty string should feel the same.
        r_config.r_set('storpool_conf', '')

        r_state.r_set_states(states['none'])
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)
        self.assertEquals(states['none'], r_state.r_get_states())
        self.assertEquals(count_npset, npset.call_count)
        self.assertEquals(count_unset + 3, unset_our_id.call_count)

        r_state.r_set_states(states['all'])
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)
        self.assertEquals(states['none'], r_state.r_get_states())
        self.assertEquals(count_npset, npset.call_count)
        self.assertEquals(count_unset + 4, unset_our_id.call_count)

        # A real value for storpool_conf
        r_state.r_set_states(states['none'])
        r_config.r_set('storpool_conf', 'something')
        testee.config_changed()
        self.assertEquals(states['got-config'], r_state.r_get_states())
        self.assertEquals(count_npset + 1, npset.call_count)
        self.assertEquals(count_unset + 5, unset_our_id.call_count)

        r_state.r_set_states(states['all'])
        r_config.r_set('storpool_conf', 'something')
        testee.config_changed()
        self.assertEquals(states['got-config'], r_state.r_get_states())
        self.assertEquals(count_npset + 2, npset.call_count)
        self.assertEquals(count_unset + 6, unset_our_id.call_count)

    @mock_reactive_states
    @mock.patch('charmhelpers.core.hookenv.config', new=lambda: None)
    @mock.patch('spcharms.status.npset')
    @mock.patch('spcharms.repo.install_packages')
    @mock.patch('spcharms.repo.record_packages')
    def test_install_package(self, record_packages, install_packages, npset):
        """
        Test that the layer attempts to install packages correctly.
        """
        count_npset = npset.call_count
        count_install = install_packages.call_count
        count_record = record_packages.call_count

        # Check that it doesn't do anything without a StorPool version
        testee.install_package()
        self.assertEquals(count_npset + 1, npset.call_count)
        self.assertEquals(count_install, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

        # An empty string should feel the same...
        testee.install_package()
        self.assertEquals(count_npset + 2, npset.call_count)
        self.assertEquals(count_install, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

        # Okay, now let's give it something to install... and fail.
        r_config.r_set('storpool_version', '0.1.0')
        install_packages.return_value = ('oops', [])
        self.assertRaises(sperror.StorPoolPackageInstallException,
                          testee.install_package)
        self.assertEquals(count_npset + 4, npset.call_count)
        self.assertEquals(count_install + 1, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

        # Right, now let's pretend that there was nothing to install
        install_packages.return_value = (None, [])
        testee.install_package()
        self.assertEquals(count_npset + 7, npset.call_count)
        self.assertEquals(count_install + 2, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

        # And now for the most common case, something to install...
        r_state.r_set_states(set())
        install_packages.return_value = (None, ['storpool-beacon'])
        testee.install_package()
        self.assertEquals(count_npset + 10, npset.call_count)
        self.assertEquals(count_install + 3, install_packages.call_count)
        self.assertEquals(count_record + 1, record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

    @mock_reactive_states
    @mock.patch('charmhelpers.core.hookenv.charm_dir')
    @mock.patch('spcharms.txn.install')
    @mock.patch('spcharms.config.get_dict')
    @mock.patch('spcharms.config.set_our_id')
    def xtest_write_out_config(self, set_our_id, get_dict, txn_install,
                               charm_dir):
        """
        Test that the config file written is actually the same as
        the one supplied in the charm configuration.
        """
        conf = {
            'SP_OURID': '1',
            'SP_CLUSTER_ID': 'a.a',
        }
        conf_text = ''.join(map(lambda key: '{var}={value}\n'
                                .format(var=key, value=conf[key]),
                                sorted(conf)))
        r_config.r_set('storpool_conf', conf_text)

        def txn_check(*args):
            """
            Make sure txn.install() was invoked correctly.
            """
            self.assertTrue(len(args) >= 2)
            self.assertEqual(args[-1], '/etc/storpool.conf')
            with open(args[-2], mode='r') as f:
                contents = f.read()
                self.assertEquals(conf_text, contents)

        txn_install.side_effect = txn_check
        get_dict.return_value = conf
        set_our_id.side_effect = lambda v: \
            self.assertEquals(conf['SP_OURID'], v)
        count_set = set_our_id.call_count
        charm_dir.return_value = os.getcwd()

        testee.write_out_config()
        self.assertEquals(count_set + 1, set_our_id.call_count)
