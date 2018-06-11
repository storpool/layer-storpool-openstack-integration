"""
A StorPool Juju charm helper module for accessing the StorPool configuration.
"""
import subprocess

from charms import reactive
from charmhelpers.core import hookenv, unitdata

from spcharms import error
from spcharms import kvdata

cached_config = None
cached_meta = None
initializing_config = None


class QuasiConfig(object):
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
            return super(QuasiConfig, self).__setattr__(name, value)

        raise AttributeError('Cannot override the QuasiConfig '
                             '"{name}" attribute'.format(name=name))

    def get_dict(self):
        d = dict(self.config)
        d.update(self.override)
        return d

    def __str__(self):
        return str(self.get_dict())


def get_cached_dict():
    """
    Get the StorPool configuration, cache it the first time.
    """
    global cached_config
    if cached_config is not None:
        return cached_config

    res = {}
    lines_b = subprocess.check_output(['/usr/sbin/storpool_confshow'])
    for line in lines_b.decode().split('\n'):
        fields = line.split('=', 1)
        if len(fields) < 2:
            continue
        res[fields[0]] = fields[1]
    cached_config = res
    return cached_config


def get_dict():
    """
    Get the StorPool configuration.
    """
    return get_cached_dict()


def drop_cache():
    """
    Drop the StorPool configuration cache.
    """
    global cached_config
    cached_config = None


def get_our_id():
    """
    Fetch the cached SP_OURID value from the unit's database.
    """
    return unitdata.kv().get(kvdata.KEY_OURID, None)


def set_our_id(value):
    """
    Store the SP_OURID value into the unit's database.
    """
    unitdata.kv().set(kvdata.KEY_OURID, value)


def unset_our_id():
    """
    Store the SP_OURID value into the unit's database.
    """
    unitdata.kv().unset(kvdata.KEY_OURID)


def m():
    """
    Get the source of StorPool configuration variables, either hookenv.config()
    or the data hash specified using set_meta_config().
    """
    global cached_meta
    if cached_meta is None:
        mm = unitdata.kv().get(kvdata.KEY_META_CONFIG, None)
        if mm is None:
            raise error.StorPoolNoConfigException(['*'])
        elif mm == 'None':
            cached_meta = mm
        else:
            cfg = QuasiConfig()
            for (key, value) in mm.items():
                cfg.r_set(key, value, True)
            cached_meta = cfg

    if cached_meta == 'None':
        return hookenv.config()
    return cached_meta


def set_meta_config(data):
    """
    Specify the config dictionary that will provide the StorPool-related
    charm configuration variables.
    If specified as None, m() will use hookenv.config().
    """
    # Store the new data into the unit's database.
    if data is None:
        store = 'None'
    else:
        store = data
    unitdata.kv().set(kvdata.KEY_META_CONFIG, store)

    # Fetch it right back into a QuasiConfig object.
    global cached_meta
    cached_meta = None
    m()
    reactive.set_state('storpool-helper.config-set')


def unset_meta_config():
    """
    Forget any cached configuration data.
    """
    unitdata.kv().unset(kvdata.KEY_META_CONFIG)
    global cached_meta
    cached_meta = None
    reactive.remove_state('storpool-helper.config-set')
