#!/usr/bin/python3

"""
A set of unit tests for the storpool-openstack-integration layer.
"""

import os
import sys
import unittest

import mock

root_path = os.path.realpath('lib')
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from spcharms import error as sperror
from spcharms import utils as sputils


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


r_config = MockConfig()

# Do not give hookenv.config() a chance to run at all
# hookenv.config = lambda: r_config


def mock_reactive_states(f):
    def inner1(inst, *args, **kwargs):
        @mock.patch('spcharms.config.m', new=lambda: r_config)
        def inner2(*args, **kwargs):
            return f(inst, *args, **kwargs)

        return inner2()

    return inner1


comp = {}
comp_tester = None


def exec_with_output(cmd):
    if cmd[0] == 'env' and cmd[1].startswith('PATH='):
        cmd = cmd[2:]
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
    elif cmd[0:5] == ['sp-openstack', '-T', 'charm-storpool-block',
                      '--', 'groups']:
        comp_tester.assertIn(cmd[5], comp['all'])
        return {'res': 0}
    else:
        comp_tester.fail('Unexpected command {cmd} '
                         'passed to exec_with_output()'
                         .format(cmd=cmd))


from spcharms.run import storpool_openstack_integration as testee


class TestStorPoolOpenStack(unittest.TestCase):
    """
    Test various aspects of the storpool-openstack-integration layer.
    """
    def setUp(self):
        """
        Clean up the reactive states information between tests.
        """
        super(TestStorPoolOpenStack, self).setUp()
        r_config.r_clear_config()
        self.save_sputils_err = sputils.err
        sputils.err = lambda *args: self.fail_on_err(*args)

    def tearDown(self):
        """
        Restore the sputils.err function.
        """
        super(TestStorPoolOpenStack, self).tearDown()
        sputils.err = self.save_sputils_err

    def fail_on_err(self, msg):
        self.fail('sputils.err() invoked: {msg}'.format(msg=msg))

    @mock_reactive_states
    @mock.patch('charmhelpers.core.hookenv.config', new=lambda: {})
    def test_config_changed(self):
        """
        Test that the reactive states are properly (re)set when
        the charm configuration changes.
        """

        # Reset everything if there is no configuration
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)

        r_config.r_set('storpool_version', '', False)
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)

        r_config.r_clear_config()
        r_config.r_set('storpool_openstack_version', '', False)
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)

        r_config.r_set('storpool_version', '', False)
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)

        # ...or if only the storpool_version is defined
        r_config.r_clear_config()
        r_config.r_set('storpool_version', '0.1.0', False)
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)

        r_config.r_set('storpool_openstack_version', '', False)
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)

        # ...or if only the storpool_openstack_version is defined
        r_config.r_clear_config()
        r_config.r_set('storpool_openstack_version', '0.1.0', False)
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)

        r_config.r_set('storpool_version', '', False)
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)

        # If both are set and nothing is changed...
        r_config.r_set('storpool_version', '0.1.0', False)
        testee.config_changed()

        # But it's a little different when the configuration has
        # just changed, isn't it?  Most of it is the same...
        r_config.r_clear_config()
        r_config.r_set('storpool_version', '0.1.0', True)
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)

        r_config.r_clear_config()
        r_config.r_set('storpool_openstack_version', '0.1.0', True)
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.config_changed)

        r_config.r_set('storpool_version', '0.1.0', True)
        testee.config_changed()

    @mock_reactive_states
    @mock.patch('charmhelpers.core.hookenv.config', new=lambda: r_config)
    @mock.patch('spcharms.status.npset')
    @mock.patch('spcharms.repo.record_packages')
    @mock.patch('spcharms.repo.install_packages')
    def test_install_package(self, install_packages, record_packages, npset):
        """
        Test that the layer attempts to install packages correctly.
        """
        count_npset = npset.call_count
        count_install = install_packages.call_count
        count_record = record_packages.call_count

        # Check that it doesn't do anything without a StorPool version
        self.assertRaises(sperror.StorPoolNoConfigException,
                          testee.install_package)
        self.assertEquals(count_npset + 1, npset.call_count)
        self.assertEquals(count_install, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)

        # Now give it something to install, but tell it not to.
        r_config.r_set('storpool_version', '0.1.0', False)
        r_config.r_set('storpool_openstack_version', '3.2.1', False)
        r_config.r_set('storpool_openstack_install', False, False)
        testee.install_package()
        self.assertEquals(count_npset + 2, npset.call_count)
        self.assertEquals(count_install, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)

        def raise_spe(_):
            raise sperror.StorPoolPackageInstallException([], 'oops')

        # Okay, now let's give it something to install... and fail.
        r_config.r_clear_config()
        r_config.r_set('storpool_version', '0.1.0', False)
        r_config.r_set('storpool_openstack_version', '3.2.1', False)
        r_config.r_set('storpool_openstack_install', True, False)
        install_packages.side_effect = raise_spe
        self.assertRaises(sperror.StorPoolPackageInstallException,
                          testee.install_package)
        install_packages.side_effect = None
        self.assertEquals(count_npset + 4, npset.call_count)
        self.assertEquals(count_install + 1, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)

        # Right, now let's pretend that there was nothing to install
        install_packages.return_value = []
        testee.install_package()
        self.assertEquals(count_npset + 7, npset.call_count)
        self.assertEquals(count_install + 2, install_packages.call_count)
        self.assertEquals(count_record, record_packages.call_count)

        # And now for the most common case, something to install...
        install_packages.return_value = ['storpool-openstack-integration']
        testee.install_package()
        self.assertEquals(count_npset + 10, npset.call_count)
        self.assertEquals(count_install + 3, install_packages.call_count)
        self.assertEquals(count_record + 1, record_packages.call_count)

    # Now this one is a doozy...
    @mock_reactive_states
    @mock.patch('charmhelpers.core.hookenv.config', new=lambda: r_config)
    @mock.patch('spcharms.txn.module_name')
    @mock.patch('spcharms.config.get_our_id')
    @mock.patch('spcharms.status.npset')
    @mock.patch('os.path.exists')
    @mock.patch('os.path.isdir')
    @mock.patch('os.path.isfile')
    @mock.patch('subprocess.call')
    @mock.patch('subprocess.check_output')
    @mock.patch('spcharms.utils.exec', new=exec_with_output)
    def test_enable_and_start(self, check_output, just_call,
                              isfile, isdir, exists, npset, get_our_id,
                              txn_module_name):
        """
        Test that at least some steps are taken towards examining
        the environment and setting up some files.
        """
        count_npset = npset.call_count

        # We were not even told to do nothing, we were just told...
        # nothing...
        with self.assertRaises(KeyError):
            testee.enable_and_start()

        # OK, now we were indeed told not to do anything...
        r_config.r_set('storpool_openstack_install', False, False)
        testee.enable_and_start()
        self.assertEquals(count_npset, npset.call_count)

        # There are no containers!
        # (so, yeah, strictiy this cannot happen, there would always be
        #  the bare metal environment, but oh well)
        r_config.r_set('storpool_openstack_install', True, False)
        get_our_id.return_value = '1'
        isfile.return_value = False
        isdir.return_value = True
        exists.return_value = False
        check_output.return_value = bytes('disk\n', 'UTF-8')

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
            ) and cmd[0] != 'juju-log':
                self.fail('subprocess.call() invoked for '
                          'unexpected command {cmd}'.format(cmd=cmd))

        just_call.side_effect = subprocess_call_validate

        # Right, so let's have these...
        txn_module_name.return_value = 'charm-storpool-block'
        testee.enable_and_start()

        # Did we detect, check, and install all the necessary components?
        for tp in ('detected', 'checked', 'installed'):
            self.assertEquals(comp['all'], comp[tp])
