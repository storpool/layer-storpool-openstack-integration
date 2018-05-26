#!/usr/bin/python
"""
Set and reset states for all layers and interfaces when the charm
signals e.g. a hook firing.
"""

from charms import reactive
from charmhelpers.core import unitdata

from spcharms import kvdata
from spcharms import utils as sputils


def get_registered():
    """
    Fetch the big table of states to set and reset.
    """
    return unitdata.kv().get(kvdata.KEY_SET_STATES, {})


def set_registered(data):
    """
    Store the big table of states to set and reset.
    """
    unitdata.kv().set(kvdata.KEY_SET_STATES, data)


def register(layer, states):
    """
    Register a layer's set of states to set and unset on
    certain hooks firing.  Overrides any previously defined
    data for this layer.
    """
    data = get_registered()
    data[layer] = states
    set_registered(data)


def unregister(layer):
    """
    Unregister a layer's set of states.
    """
    data = get_registered()
    if layer in data:
        del data[layer]
        set_registered(data)


def handle_single(data):
    """
    Set or unset states as specified.
    """
    for (key, value) in data.items():
        if key == 'set':
            for state in value:
                reactive.set_state(state)
        elif key == 'unset':
            for state in value:
                reactive.remove_state(state)
        else:
            sputils.err('Invalid states array key: "{key}"'.format(key=key))
            return


def handle_event(event):
    """
    Set or reset states for all the registered layers that
    handle the specified event.
    """
    for (_, states) in get_registered().items():
        data = states.get(event, None)
        if data is None:
            continue
        handle_single(data)
