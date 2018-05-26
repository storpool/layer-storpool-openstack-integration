"""
A StorPool Juju charm helper module: persistent unit status message.
"""

from charmhelpers.core import hookenv, unitdata

from spcharms import kvdata


def get():
    """
    Get the persistent status as a (status, message) tuple or None.
    """
    st = unitdata.kv().get(kvdata.KEY_SPSTATUS, default=None)
    if st is None:
        return None
    return st.split(':', 1)


def set(status, msg):
    """
    Set a persistent status and message.

    The special `status` value of "error" is used to indicate a persistent
    error (see the `reset_unless_error()` function below); the unit status
    itself is set to "maintenance" instead.
    """
    hookenv.status_set(status if status != 'error' else 'maintenance', msg)
    unitdata.kv().set(kvdata.KEY_SPSTATUS, status + ':' + msg)


def reset():
    """
    Remove a persistent status.
    """
    unitdata.kv().unset(kvdata.KEY_SPSTATUS)


def reset_unless_error():
    """
    Remove a persistent status unless it signifies an error.
    """
    st = get()
    if st is None or st[0] != 'error':
        reset()
        hookenv.status_set('maintenance', '')


def npset(status, message):
    """
    Set the unit's status if no persistent status has been set.
    """
    if not get():
        hookenv.status_set(status, message)


def set_status_reset_handler(name):
    """
    Store the specified layer name as the layer that is allowed to reset
    the status even if a persistent one has been set.
    """
    unitdata.kv().set(kvdata.KEY_SPSTATUS, name)


def reset_if_allowed(name):
    """
    Reset the persistent status if the layer with the specified name has
    previously been set as the one that is allowed to.
    """
    stored = unitdata.kv().get(kvdata.KEY_SPSTATUS, '')
    if name == stored:
        reset()
