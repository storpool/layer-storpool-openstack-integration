#!/usr/bin/python3

"""
A set of unit tests for the spcharms.config class that
parses the output of the storpool_confshow command.
"""

import os
import sys
import unittest

import mock
import six

lib_path = os.path.realpath('lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from spcharms import config as spconfig


test_config = {
    'simple': 'string',
    'integer': '42',
}

test_config_string = ''.join(map(lambda i: '{var}={val}\n'.format(var=i[0],
                                                                  val=i[1]),
                                 six.iteritems(test_config)))
test_config_bytes = six.b(test_config_string)

test_other_config = {
    'something': 'else',
    'but': 'really',
}


class TestConfig(unittest.TestCase):
    def setUp(self):
        """
        Clear the cached configuration between tests.
        """
        super(TestConfig, self).setUp()
        spconfig.cached_config = None

    @mock.patch('subprocess.check_output')
    def do_test_get_dict(self, get_dict, check_output):
        """
        Parse some real storpool_confshow-like output.
        """
        # In the beginning, the...re was no cached config.
        self.assertIsNone(spconfig.cached_config)

        # Let it try to run storpool_confshow
        check_output.return_value = test_config_bytes
        res = get_dict()
        check_output.assert_called_once_with(['/usr/sbin/storpool_confshow'])

        # Make sure it parsed our configuration data correctly
        self.assertEqual(res, test_config)
        self.assertEqual(spconfig.cached_config, test_config)

        # Let's hope it doesn't run storpool_confshow any more
        res = get_dict()
        check_output.assert_called_once_with(['/usr/sbin/storpool_confshow'])

        # But it still returns the same data
        self.assertEqual(res, test_config)
        self.assertEqual(spconfig.cached_config, test_config)

        # Okay, now make it return different data
        spconfig.cached_config = test_other_config
        res = get_dict()
        check_output.assert_called_once_with(['/usr/sbin/storpool_confshow'])
        self.assertEqual(res, test_other_config)
        self.assertEqual(spconfig.cached_config, test_other_config)

        # Right, now let's see if it will call storpool_confshow again
        spconfig.cached_config = None
        res = get_dict()
        self.assertEqual(check_output.call_count, 2)
        check_output.assert_called_with(['/usr/sbin/storpool_confshow'])
        self.assertEqual(res, test_config)
        self.assertEqual(spconfig.cached_config, test_config)

    def test_get_cached_dict(self):
        """
        Make sure spconfig.get_cached_dict() behaves.
        """
        self.do_test_get_dict(spconfig.get_cached_dict)

    def test_get_dict(self):
        """
        Make sure spconfig.get_dict() behaves.
        """
        self.do_test_get_dict(spconfig.get_dict)

    @mock.patch('subprocess.check_output')
    def test_drop_cache(self, check_output):
        """
        Make sure drop_cache() actually, well, drops the cache.
        """
        # In the beginning, the...re was no cached config.
        self.assertIsNone(spconfig.cached_config)

        # Let it try to run storpool_confshow
        check_output.return_value = test_config_bytes
        res = spconfig.get_cached_dict()
        check_output.assert_called_once_with(['/usr/sbin/storpool_confshow'])

        # Make sure it parsed our configuration data correctly
        self.assertEqual(res, test_config)
        self.assertEqual(spconfig.cached_config, test_config)

        # Right, let's go
        spconfig.drop_cache()
        self.assertIsNone(spconfig.cached_config)
