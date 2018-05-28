#!/usr/bin/python3

"""
A set of unit tests for the storpool-block layer.
"""

import os
import sys
import unittest

import mock

root_path = os.path.realpath('lib')
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from spcharms import error as sperror


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


from reactive import storpool_block as testee

STARTED_STATE = 'storpool-block.block-started'


class TestStorPoolBlock(unittest.TestCase):
    """
    Test various aspects of the storpool-block layer.
    """
    def setUp(self):
        """
        Clean up the reactive states information between tests.
        """
        super(TestStorPoolBlock, self).setUp()
        r_state.r_clear_states()

    @mock_reactive_states
    @mock.patch('charmhelpers.core.hookenv.config', new=lambda: r_config)
    @mock.patch('spcharms.repo.record_packages')
    @mock.patch('spcharms.repo.install_packages')
    @mock.patch('spcharms.status.npset')
    @mock.patch('spcharms.utils.check_in_lxc')
    def test_install_package(self, check_in_lxc, npset,
                             install_packages, record_packages):
        """
        Test that the layer attempts to install packages correctly.
        """
        count_in_lxc = check_in_lxc.call_count
        count_npset = npset.call_count
        count_install = install_packages.call_count
        count_record = record_packages.call_count

        # First, make sure it does nothing in a container.
        r_state.r_set_states(set())
        check_in_lxc.return_value = True
        testee.install_package()
        self.assertEquals(count_in_lxc + 1, check_in_lxc.call_count)
        self.assertEquals(count_npset, npset.call_count)
        self.assertEquals(count_install, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

        # Check that it doesn't do anything without a StorPool version
        r_state.r_set_states(set())
        r_config.r_clear_config()
        check_in_lxc.return_value = False
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.install_package)
        self.assertEquals(count_in_lxc + 2, check_in_lxc.call_count)
        self.assertEquals(count_npset + 1, npset.call_count)
        self.assertEquals(count_install, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

        def raise_spe(_):
            raise sperror.StorPoolPackageInstallException([], 'oops')

        # Okay, now let's give it something to install... and fail.
        r_config.r_set('storpool_version', '0.1.0', False)
        install_packages.side_effect = raise_spe
        self.assertRaises(sperror.StorPoolPackageInstallException,
                          testee.install_package)
        install_packages.side_effect = None
        self.assertEquals(count_in_lxc + 3, check_in_lxc.call_count)
        self.assertEquals(count_npset + 3, npset.call_count)
        self.assertEquals(count_install + 1, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

        # Right, now let's pretend that there was nothing to install
        install_packages.return_value = []
        testee.install_package()
        self.assertEquals(count_in_lxc + 4, check_in_lxc.call_count)
        self.assertEquals(count_npset + 6, npset.call_count)
        self.assertEquals(count_install + 2, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

        # And now for the most common case, something to install...
        r_state.r_set_states(set())
        install_packages.return_value = ['storpool-beacon']
        testee.install_package()
        self.assertEquals(count_in_lxc + 5, check_in_lxc.call_count)
        self.assertEquals(count_npset + 9, npset.call_count)
        self.assertEquals(count_install + 3, install_packages.call_count)
        self.assertEquals(count_record + 1, record_packages.call_count)
        self.assertEquals(set(), r_state.r_get_states())

    @mock_reactive_states
    @mock.patch('charmhelpers.core.hookenv.config', new=lambda: r_config)
    @mock.patch('charmhelpers.core.host.service_resume')
    @mock.patch('os.path.isfile')
    @mock.patch('spcharms.utils.check_cgroups')
    @mock.patch('spcharms.utils.check_in_lxc')
    def test_enable_and_start(self, check_in_lxc, check_cgroups,
                              isfile, service_resume):
        """
        Test that the layer enables the system startup service.
        """
        count_in_lxc = check_in_lxc.call_count
        count_cgroups = check_cgroups.call_count

        # First, make sure it does nothing in a container.
        r_state.r_set_states(set())
        check_in_lxc.return_value = True
        testee.enable_and_start()
        self.assertEquals(count_in_lxc + 1, check_in_lxc.call_count)
        self.assertEquals(count_cgroups, check_cgroups.call_count)
        self.assertEquals(set([STARTED_STATE]), r_state.r_get_states())

        def raise_cge(_):
            raise sperror.StorPoolNoCGroupsException('oops')

        # Now make sure it doesn't start if it can't find its control group.
        r_state.r_set_states(set())
        check_in_lxc.return_value = False
        check_cgroups.side_effect = raise_cge
        self.assertRaises(sperror.StorPoolNoCGroupsException,
                          testee.enable_and_start)
        check_cgroups.side_effect = None
        self.assertEquals(count_in_lxc + 2, check_in_lxc.call_count)
        self.assertEquals(count_cgroups + 1, check_cgroups.call_count)
        self.assertEquals(set(), r_state.r_get_states())

        # And now let it run... first without storpool_stat...
        r_state.r_set_states(set())
        check_in_lxc.return_value = False
        check_cgroups.return_value = True
        isfile.return_value = False
        testee.enable_and_start()
        self.assertEquals(count_in_lxc + 3, check_in_lxc.call_count)
        self.assertEquals(count_cgroups + 2, check_cgroups.call_count)
        service_resume.assert_called_once_with('storpool_block')
        self.assertEquals(set([STARTED_STATE]), r_state.r_get_states())

        # ...and then with it.
        r_state.r_set_states(set())
        check_in_lxc.return_value = False
        check_cgroups.return_value = True
        isfile.return_value = True
        testee.enable_and_start()
        self.assertEquals(count_in_lxc + 4, check_in_lxc.call_count)
        self.assertEquals(count_cgroups + 3, check_cgroups.call_count)
        self.assertEquals(3, service_resume.call_count)
        self.assertEquals(set([STARTED_STATE]), r_state.r_get_states())