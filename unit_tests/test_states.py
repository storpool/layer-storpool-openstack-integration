#!/usr/bin/python3

"""
A set of unit tests for the spcharms.states class that
records and fires events.
"""

import os
import sys
import unittest

import mock

from spcharms import kvdata


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


class MockDB(object):
    """
    A simple replacement for unitdata.kv's get() and set() methods,
    along with some helper methods for testing.
    """
    def __init__(self, **data):
        """
        Initialize a dictionary-like object with the specified key/value pairs.
        """
        self.data = dict(data)

    def get(self, name, default=None):
        """
        Get the value for the specified key with a fallback default.
        """
        return self.data.get(name, default)

    def set(self, name, value):
        """
        Set the value for the specified key.
        """
        self.data[name] = value

    def r_get_all(self):
        """
        For testing purposes: return a shallow copy of the whole dictinary.
        """
        return dict(self.data)

    def r_set_all(self, data):
        """
        For testing purposes: set the stored data to a shallow copy of
        the supplied dictionary.
        """
        self.data = dict(data)

    def r_clear(self):
        """
        For testing purposes: remove all key/value pairs.
        """
        self.data = {}


r_state = MockReactive()
r_kv = MockDB()


def mock_reactive_states(f):
    def inner1(inst, *args, **kwargs):
        @mock.patch('charmhelpers.core.unitdata.kv', new=lambda: r_kv)
        @mock.patch('charms.reactive.set_state', new=r_state.set_state)
        @mock.patch('charms.reactive.remove_state', new=r_state.remove_state)
        @mock.patch('charms.reactive.helpers.is_state', new=r_state.is_state)
        def inner2(*args, **kwargs):
            return f(inst, *args, **kwargs)

        return inner2()

    return inner1


lib_path = os.path.realpath('lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from spcharms import states as testee


class TestStates(unittest.TestCase):
    def setUp(self):
        """
        Clear the state between tests.
        """
        super(TestStates, self).setUp()
        r_state.r_set_states(set())
        r_kv.r_clear()

    @mock_reactive_states
    def test_get_set(self):
        """
        Make sure that get_registered() returns exactly the same data as
        set_registered().
        """
        for v in (None, 'a', 1, ['a', 1], {'a': ['a', 1]}):
            testee.set_registered(v)
            self.assertEqual(v, testee.get_registered())
            self.assertEqual({kvdata.KEY_SET_STATES: v}, r_kv.r_get_all())
            self.assertEqual(set(), r_state.r_get_states())

    @mock_reactive_states
    def test_register_unregister(self):
        """
        Test register() and unregister().
        """
        testee.register('a', 'aa')
        self.assertEqual({'a': 'aa'}, testee.get_registered())
        self.assertEqual(set(), r_state.r_get_states())

        testee.register('b', 'bb')
        self.assertEqual({'a': 'aa', 'b': 'bb'}, testee.get_registered())
        self.assertEqual(set(), r_state.r_get_states())

        testee.register('a', -1)
        self.assertEqual({'a': -1, 'b': 'bb'}, testee.get_registered())
        self.assertEqual(set(), r_state.r_get_states())

        testee.unregister('b')
        self.assertEqual({'a': -1}, testee.get_registered())
        self.assertEqual(set(), r_state.r_get_states())

        testee.register('c', set('c'))
        self.assertEqual({'a': -1, 'c': set('c')}, testee.get_registered())
        self.assertEqual(set(), r_state.r_get_states())

        testee.unregister('b')
        self.assertEqual({'a': -1, 'c': set('c')}, testee.get_registered())
        self.assertEqual(set(), r_state.r_get_states())

        testee.unregister('a')
        self.assertEqual({'c': set('c')}, testee.get_registered())
        self.assertEqual(set(), r_state.r_get_states())

        testee.unregister('c')
        self.assertEqual({}, testee.get_registered())
        self.assertEqual(set(), r_state.r_get_states())

        testee.unregister('a')
        testee.unregister('b')
        testee.unregister('c')
        testee.unregister('d')
        self.assertEqual({}, testee.get_registered())
        self.assertEqual(set(), r_state.r_get_states())

    @mock_reactive_states
    def test_handle_events(self):
        """
        Test a full lifecycle of events handling.
        """
        states = {
            'f-conf-set': set(['first.configure']),
            'f-conf-unset': set(['first.configured', 'first.installed']),
            'f-up-set': set(['first.configure', 'first.upgrade']),
            'f-up-unset': set(['first.configured', 'first.installed']),
            's-conf-set': set(['second.configure']),
            's-conf-unset': set([
                'second.configured',
                'second.started',
                'second.submitted',
            ]),
            's-start-set': set(['second.started']),
            's-start-unset': set(['second.submitted']),
        }

        s_all = set()
        for key in states:
            s_all = s_all.union(states[key])
        states['all'] = s_all

        states['pre-conf'] = s_all \
            .difference(states['f-conf-set']) \
            .difference(states['s-conf-set'])
        states['post-conf'] = s_all \
            .difference(states['f-conf-unset']) \
            .difference(states['s-conf-unset'])
        self.assertNotEqual(states['all'], states['pre-conf'])
        self.assertNotEqual(states['all'], states['post-conf'])
        self.assertNotEqual(states['pre-conf'], states['post-conf'])

        states['post-conf-start'] = states['post-conf'] \
            .difference(states['s-start-unset']) \
            .union(states['s-start-set'])
        self.assertNotEqual(states['post-conf-start'], states['post-conf'])
        self.assertNotEqual(states['post-conf-start'], states['all'])

        testee.register('first', {
            'config-changed': {
                'set': states['f-conf-set'],
                'unset': states['f-conf-unset'],
            },

            'upgrade-charm': {
                'set': states['f-up-set'],
                'unset': states['f-up-unset'],
            },
        })
        self.assertEqual(['first'],
                         sorted(r_kv.get(kvdata.KEY_SET_STATES).keys()))
        self.assertEqual(set(), r_state.r_get_states())

        testee.register('second', {
            'config-changed': {
                'set': states['s-conf-set'],
                'unset': states['s-conf-unset'],
            },

            'start': {
                'set': states['s-start-set'],
                'unset': states['s-start-unset'],
            },
        })
        self.assertEqual(['first', 'second'],
                         sorted(r_kv.get(kvdata.KEY_SET_STATES).keys()))
        self.assertEqual(set(), r_state.r_get_states())

        # Now let's go
        r_state.r_set_states(states['pre-conf'])

        testee.handle_event('config-changed')
        self.assertEqual(states['post-conf'], r_state.r_get_states())

        testee.handle_event('start')
        self.assertEqual(states['post-conf-start'], r_state.r_get_states())

        r_state.r_clear_states()
        testee.handle_event('config-changed')
        self.assertEqual(states['f-conf-set'].union(states['s-conf-set']),
                         r_state.r_get_states())
