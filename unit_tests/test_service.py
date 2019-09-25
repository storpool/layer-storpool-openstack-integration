#!/usr/bin/python3

"""
A set of unit tests for the storpool-service layer.
"""

import os
import sys
import unittest

import copy
import ddt


lib_path = os.path.realpath("lib")
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from spcharms import service_hook as testee


STORPOOL_PRESENCE_DATA = {
    "format": {"version": {"major": 1, "minor": 0}},
    "generation": 5,
    "nodes": {
        "block:1": {"hostname": "ostack1", "id": "41", "generation": 1},
        "block:2": {"hostname": "ostack2", "id": "42", "generation": 2},
        "cinder:1": {"hostname": "ostack1", "generation": 3},
    },
}


SCHEMA = {
    "simple": {"integer": int, "string": str, "?q": str},
    "sub": {"gen": int, "n": {"name": str}},
    "star": {"gen": int, "nodes": {"*": {"name": str}}},
}


@ddt.ddt
class TestStorPoolService(unittest.TestCase):
    """
    Test various aspects of the storpool-service layer.
    """

    @ddt.data(
        # A trivial schema
        # - missing elements
        ("simple", {}, testee.ValidationError),
        ("simple", {"integer": 1}, testee.ValidationError),
        ("simple", {"string": "2"}, testee.ValidationError),
        # - wrong type
        ("simple", {"integer": 3, "string": 4}, testee.ValidationError),
        (
            "simple",
            {"integer": 5, "string": "6", "q": 7},
            testee.ValidationError,
        ),
        ("simple", {"integer": "8", "string": "9"}, testee.ValidationError),
        # - extra elements
        (
            "simple",
            {"integer": 10, "string": "11", "a": 12},
            testee.ValidationError,
        ),
        # - fine
        ("simple", {"integer": 10, "string": "11"}, None),
        ("simple", {"integer": 12, "string": "13", "q": "14"}, None),
        # OK, recursive calls now...
        # - missing elements
        ("sub", {}, testee.ValidationError),
        ("sub", {"gen": 1}, testee.ValidationError),
        ("sub", {"gen": 2, "nodes": {}}, testee.ValidationError),
        ("sub", {"nodes": {"name": "3"}}, testee.ValidationError),
        # - wrong type
        ("sub", {"gen": "4", "nodes": {"name": "5"}}, testee.ValidationError),
        ("sub", {"gen": 6, "nodes": {"name": 7}}, testee.ValidationError),
        # - extra elements
        (
            "sub",
            {"gen": 8, "nodes": {"name": "9"}, "x": 10},
            testee.ValidationError,
        ),
        (
            "sub",
            {"gen": 11, "nodes": {"name": "12", "x": 13}},
            testee.ValidationError,
        ),
        # - fine
        ("sub", {"gen": 14, "n": {"name": "15"}}, None),
        # Real dictionaries now
        # - missing elements
        ("star", {}, testee.ValidationError),
        ("star", {"gen": 1, "nodes": {"2": {}}}, testee.ValidationError),
        (
            "star",
            {"gen": 1, "nodes": {"2": {"name": "3"}, "4": {"name": "5"}}},
            None,
        ),
    )
    @ddt.unpack
    def test_validate_dict(self, schema, data, exc):
        sch = SCHEMA[schema]
        if exc is None:
            testee.validate_dict(data, sch)
        else:
            self.assertRaises(exc, testee.validate_dict, data, sch)

    @ddt.data(
        ("format", None, testee.ValidationError),
        ("format/version", None, testee.ValidationError),
        ("format/version/major", None, testee.ValidationError),
        ("format/version/major", -3, testee.UnsupportedFormatError),
        ("format/version/major", 0, testee.UnsupportedFormatError),
        ("format/version/major", 2, testee.UnsupportedFormatError),
        ("format/version/minor", -3, testee.UnsupportedFormatError),
        ("format/version/minor", 0, None),
        ("format/version/minor", 42, None),
        ("generation", "whee", testee.ValidationError),
        ("extra", "extra", testee.ValidationError),
        ("nodes/block:1/extra", "extra", testee.ValidationError),
        ("nodes/block:2/generation", "", testee.ValidationError),
    )
    @ddt.unpack
    def test_validate_block_presence(self, what, repl, exc):
        data = copy.deepcopy(STORPOOL_PRESENCE_DATA)
        where = data
        what = what.split("/")
        last = what.pop()
        for k in what:
            where = where[k]
        if repl is None:
            del where[last]
        else:
            where[last] = repl

        if exc is None:
            self.assertIs(testee.validate_storpool_presence(data), data)
        else:
            self.assertRaises(exc, testee.validate_storpool_presence, data)
