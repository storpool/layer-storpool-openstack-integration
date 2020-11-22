"""
A StorPool Juju charm helper module for accessing the StorPool configuration.
"""

from charmhelpers.core import unitdata

from spcharms import kvdata


def get_meta_generation():
    return unitdata.kv().get(kvdata.KEY_META_GENERATION)


def set_meta_generation(gen):
    unitdata.kv().set(kvdata.KEY_META_GENERATION, gen)


def unset_meta_generation():
    unitdata.kv().unset(kvdata.KEY_META_GENERATION)
