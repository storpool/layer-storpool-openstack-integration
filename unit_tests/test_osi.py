#!/usr/bin/python3

"""
A set of unit tests for the storpool-openstack-integration layer.
"""

import os
import sys
import unittest

import mock

from charmhelpers.core import hookenv

root_path = os.path.realpath('.')
if root_path not in sys.path:
    sys.path.insert(0, root_path)

lib_path = os.path.realpath('unit_tests/lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from spcharms import config as spconfig
from spcharms import repo as sprepo
from spcharms import status as spstatus
from spcharms import txn
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

# Do not give hookenv.config() a chance to run at all
hookenv.config = lambda: r_config


def mock_reactive_states(f):
    def inner1(inst, *args, **kwargs):
        @mock.patch('charms.reactive.set_state', new=r_state.set_state)
        @mock.patch('charms.reactive.remove_state', new=r_state.remove_state)
        @mock.patch('charms.reactive.helpers.is_state', new=r_state.is_state)
        def inner2(*args, **kwargs):
            return f(inst, *args, **kwargs)

        return inner2()

    return inner1


comp = {}
comp_tester = None


def exec_with_output(cmd):
    if cmd[0:3] == ['sp-openstack', '--', 'detect']:
        comp_tester.assertEqual(4, len(cmd))
        if cmd[3] in comp['all']:
            comp['detected'].add(cmd[3])
            return {'res': 0}
        else:
            return {'res': 1}
    elif cmd[0:3] == ['sp-openstack', '--', 'check']:
        # Always try to install
        comp_tester.assertIn(cmd[3], comp['all'])
        comp['checked'].add(cmd[3])
        return {'res': 1}
    elif cmd[0:5] == ['sp-openstack', '-T', 'charm-storpool-block',
                      '--', 'install']:
        comp_tester.assertIn(cmd[5], comp['all'])
        comp['installed'].add(cmd[5])
        return {'res': 0}
    else:
        comp_tester.fail('Unexpected command {cmd} '
                         'passed to exec_with_output()'
                         .format(cmd=cmd))


from reactive import storpool_openstack_integration as testee

CONFIG_STATE = 'storpool-osi.config-available'
INSTALLED_STATE = 'storpool-osi.package-installed'


class TestStorPoolOpenStack(unittest.TestCase):
    """
    Test various aspects of the storpool-openstack-integration layer.
    """
    def setUp(self):
        """
        Clean up the reactive states information between tests.
        """
        super(TestStorPoolOpenStack, self).setUp()
        r_state.r_clear_states()
        r_config.r_clear_config()
        sputils.err.side_effect = lambda *args: self.fail_on_err(*args)

    def fail_on_err(self, msg):
        self.fail('sputils.err() invoked: {msg}'.format(msg=msg))

    @mock_reactive_states
    def test_config_changed(self):
        """
        Test that the reactive states are properly (re)set when
        the charm configuration changes.
        """
        states = {
            'all': set([CONFIG_STATE, INSTALLED_STATE]),
        }

        # Reset everything if there is no configuration
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(set(), r_state.r_get_states())

        r_config.r_set('storpool_version', '', False)
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(set(), r_state.r_get_states())

        r_config.r_clear_config()
        r_config.r_set('storpool_openstack_version', '', False)
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(set(), r_state.r_get_states())

        r_config.r_set('storpool_version', '', False)
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(set(), r_state.r_get_states())

        # ...or if only the storpool_version is defined
        r_config.r_clear_config()
        r_config.r_set('storpool_version', '0.1.0', False)
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(set(), r_state.r_get_states())

        r_config.r_set('storpool_openstack_version', '', False)
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(set(), r_state.r_get_states())

        # ...or if only the storpool_openstack_version is defined
        r_config.r_clear_config()
        r_config.r_set('storpool_openstack_version', '0.1.0', False)
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(set(), r_state.r_get_states())

        r_config.r_set('storpool_version', '', False)
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(set(), r_state.r_get_states())

        # If both are set and nothing is changed...
        # ...we either set the config state...
        r_state.r_set_states(set())
        r_config.r_set('storpool_version', '0.1.0', False)
        testee.config_changed()
        self.assertEquals(set([CONFIG_STATE]), r_state.r_get_states())

        # ...or at least we do not remove it...
        testee.config_changed()
        self.assertEquals(set([CONFIG_STATE]), r_state.r_get_states())

        # ...or we preserve both states
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(states['all'], r_state.r_get_states())

        # ...or at least we set the configured one
        r_state.r_set_states(set([INSTALLED_STATE]))
        testee.config_changed()
        self.assertEquals(states['all'], r_state.r_get_states())

        # But it's a little different when the configuration has
        # just changed, isn't it?  Most of it is the same...
        r_config.r_clear_config()
        r_config.r_set('storpool_version', '0.1.0', True)
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(set(), r_state.r_get_states())

        r_config.r_clear_config()
        r_config.r_set('storpool_openstack_version', '0.1.0', True)
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(set(), r_state.r_get_states())

        r_state.r_set_states(set())
        r_config.r_set('storpool_version', '0.1.0', True)
        testee.config_changed()
        self.assertEquals(set([CONFIG_STATE]), r_state.r_get_states())

        testee.config_changed()
        self.assertEquals(set([CONFIG_STATE]), r_state.r_get_states())

        # ...but here comes the difference: if the software versions
        # have changed, we reset the "installed" state since, well,
        # we just might need to install different versions.
        r_state.r_set_states(states['all'])
        testee.config_changed()
        self.assertEquals(set([CONFIG_STATE]), r_state.r_get_states())

        r_state.r_set_states(set([INSTALLED_STATE]))
        testee.config_changed()
        self.assertEquals(set([CONFIG_STATE]), r_state.r_get_states())

    @mock_reactive_states
    def test_install_package(self):
        """
        Test that the layer attempts to install packages correctly.
        """
        count_npset = spstatus.npset.call_count
        count_install = sprepo.install_packages.call_count
        count_record = sprepo.record_packages.call_count

        # Check that it doesn't do anything without a StorPool version
        testee.install_package()
        self.assertEquals(count_npset + 1, spstatus.npset.call_count)
        self.assertEquals(count_install, sprepo.install_packages.call_count)
        self.assertEquals(count_record, sprepo.record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

        # Now give it something to install, but tell it not to.
        r_config.r_set('storpool_version', '0.1.0', False)
        r_config.r_set('storpool_openstack_version', '3.2.1', False)
        r_config.r_set('storpool_openstack_install', False, False)
        testee.install_package()
        self.assertEquals(count_npset + 2, spstatus.npset.call_count)
        self.assertEquals(count_install, sprepo.install_packages.call_count)
        self.assertEquals(count_record, sprepo.record_packages.call_count)
        self.assertEquals(set([INSTALLED_STATE]), r_state.r_get_states())

        # Okay, now let's give it something to install... and fail.
        r_state.r_set_states(set())
        r_config.r_clear_config()
        r_config.r_set('storpool_version', '0.1.0', False)
        r_config.r_set('storpool_openstack_version', '3.2.1', False)
        r_config.r_set('storpool_openstack_install', True, False)
        sprepo.install_packages.return_value = ('oops', [])
        testee.install_package()
        self.assertEquals(count_npset + 4, spstatus.npset.call_count)
        self.assertEquals(count_install + 1,
                          sprepo.install_packages.call_count)
        self.assertEquals(count_record, sprepo.record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

        # Right, now let's pretend that there was nothing to install
        sprepo.install_packages.return_value = (None, [])
        testee.install_package()
        self.assertEquals(count_npset + 7, spstatus.npset.call_count)
        self.assertEquals(count_install + 2,
                          sprepo.install_packages.call_count)
        self.assertEquals(count_record, sprepo.record_packages.call_count)
        self.assertEquals(set([INSTALLED_STATE]), r_state.r_get_states())

        # And now for the most common case, something to install...
        r_state.r_set_states(set())
        sprepo.install_packages.return_value = (
            None,
            ['storpool-openstack-integration']
        )
        testee.install_package()
        self.assertEquals(count_npset + 10, spstatus.npset.call_count)
        self.assertEquals(count_install + 3,
                          sprepo.install_packages.call_count)
        self.assertEquals(count_record + 1, sprepo.record_packages.call_count)
        self.assertEquals(set([INSTALLED_STATE]), r_state.r_get_states())

    # Now this one is a doozy...
    @mock_reactive_states
    @mock.patch('os.path.exists')
    @mock.patch('os.path.isdir')
    @mock.patch('os.path.isfile')
    @mock.patch('subprocess.call')
    @mock.patch('subprocess.check_output')
    @mock.patch('spcharms.utils.exec', new=exec_with_output)
    def test_enable_and_start(self, check_output, just_call,
                              isfile, isdir, exists):
        """
        Test that at least some steps are taken towards examining
        the environment and setting up some files.
        """
        count_npset = spstatus.npset.call_count

        # We were not even told to do nothing, we were just told...
        # nothing...
        with self.assertRaises(KeyError):
            testee.enable_and_start()

        # OK, now we were indeed told not to do anything...
        r_config.r_set('storpool_openstack_install', False, False)
        testee.enable_and_start()
        self.assertEquals(count_npset, spstatus.npset.call_count)

        # There are no containers!
        # (so, yeah, strictiy this cannot happen, there would always be
        #  the bare metal environment, but oh well)
        r_config.r_set('storpool_openstack_install', True, False)
        spconfig.get_our_id.return_value = '1'
        isfile.return_value = False
        isdir.return_value = True
        exists.return_value = False

        global comp
        comp = {
            'all': set(['nova', 'os_brick']),
            'detected': set(),
            'checked': set(),
            'installed': set(),
        }
        global comp_tester
        comp_tester = self

        def subprocess_call_validate(cmd, **kwargs):
            if cmd not in (
                ['service', 'nova-compute', 'restart'],
            ):
                self.fail('subprocess.call() invoked for '
                          'unexpected command {cmd}'.format(cmd=cmd))

        just_call.side_effect = subprocess_call_validate

        # Right, so let's have these...
        txn.module_name.return_value = 'charm-storpool-block'
        testee.enable_and_start()

        # Did we detect, check, and install all the necessary components?
        for tp in ('detected', 'checked', 'installed'):
            self.assertEquals(comp['all'], comp[tp])
