"""
A StorPool Juju charms helper module that keeps track of peer units of
the same charm so that the state may be reported to other charms.
"""
import json

from charmhelpers.core import hookenv

from spcharms import utils as sputils


def rdebug(s):
    sputils.rdebug(s, prefix='service')


STORPOOL_PRESENCE_SCHEMA_1_0 = {
    'format': {
        'version': {
            'major': int,
            'minor': int,
        },
    },

    'generation': int,

    'nodes': {
        '*': {
            'generation': int,
            'hostname': str,

            # Only for storpool-block
            '?id': str,

            # Only for the storpool-block leader
            '?config': {
                'storpool_repo_url': str,
                'storpool_version': str,
                'storpool_openstack_version': str,
                'storpool_conf': str,
            },
        },
    },
}


class UnsupportedFormatError(Exception):
    pass


class ValidationError(Exception):
    def __init__(self, key, err):
        self.key = key
        self.err = err

    def __str__(self):
        if self.key is None:
            return self.err
        else:
            return self.key + ': ' + self.err


def validate_dict(value, schema):
    if not isinstance(value, dict):
        raise ValidationError(None,
                              'not a dictionary, {t} instead'
                              .format(t=type(value).__name__))

    if len(schema.keys()) == 1 and '*' in schema:
        v_schema = schema['*']
        for key in value.keys():
            try:
                validate_dict(value[key], v_schema)
            except ValidationError as e:
                raise ValidationError(key, str(e))
        return

    extra = set(value.keys())
    for key in schema.keys():
        t = schema[key]
        if key.startswith('?'):
            required = False
            key = key[1:]
        else:
            required = True

        if key not in value:
            if required:
                raise ValidationError(key, 'missing')
            else:
                continue
        v = value[key]
        extra.remove(key)

        if isinstance(t, type):
            if not isinstance(v, t):
                raise ValidationError(key,
                                      'not a {t}, {vt} instead'
                                      .format(t=t.__name__,
                                              vt=type(v).__name__))
        else:
            assert(isinstance(t, dict))
            try:
                validate_dict(v, t)
            except ValidationError as e:
                raise ValidationError(key, str(e))

    if extra:
        raise ValidationError(None,
                              'extra keys: {lst}'.format(lst=sorted(extra)))


def validate_storpool_presence(value):
    try:
        version = value['format']['version']
        v_major = version['major']
        v_minor = int(version['minor'])
    except Exception:
        raise ValidationError(None, 'could not parse format/version')

    if v_major < 1 or v_minor < 0 or v_major > 1:
        raise UnsupportedFormatError()
    else:
        assert(v_major == 1)
        # Eh, let's hope v_minor == 0 or we can ignore the new fields.
        validate_dict(value, STORPOOL_PRESENCE_SCHEMA_1_0)
        # No need to shuffle any fields around, this is the current format.
        return value


def presence_update(relname, data):
    for name in (hookenv.relation_ids(relname) or []):
        for unit in (hookenv.related_units(name) or []):
            value = hookenv.relation_get('presence', rid=name, unit=unit)
            if value is None:
                continue
            try:
                value = json.loads(value)
                value = validate_storpool_presence(value)
            except UnsupportedFormatError:
                hookenv.log('Unsupported presence format from node {u} on ' +
                            'relation {name}'.format(u=unit, name=name),
                            hookenv.ERROR)
                continue
            except ValidationError as e:
                hookenv.log('Invalid presence data from node {u} on ' +
                            'relation {name}: {e}'
                            .format(u=unit, name=name, e=e),
                            hookenv.ERROR)
                continue
            except Exception as e:
                hookenv.log('Could not unserialize the presence data from ' +
                            'unit {u} on relation {name}: {e}'
                            .format(name=name, u=unit, e=e),
                            hookenv.ERROR)
                continue

            # Anything newer than what we have?
            if value['generation'] > data['generation']:
                data['generation'] = value['generation']

            for node in value['nodes']:
                v = value['nodes'][node]
                c_node = data['nodes'].get(node, {'generation': -1})
                current = c_node['generation']
                if current < v['generation']:
                    data['nodes'][node] = v

    return data


def presence_send(relname, data):
    for name in (hookenv.relation_ids(relname) or []):
        try:
            hookenv.relation_set(relation_id=name, relation_settings=data)
        except Exception as e:
            hookenv.log('Could not send the presence data out on ' +
                        'the {name} relation: {e}'.format(name=name, e=e),
                        hookenv.ERROR)


def fetch_presence(relations):
    data = {
        'generation': -1,
        'nodes': {},
    }
    for rel in relations:
        data = presence_update(rel, data)
    return data


def send_presence(data, relations):
    out = {
        'presence': json.dumps({
            'format': {
                'version': {
                    'major': 1,
                    'minor': 0,
                },
            },

            'generation': data['generation'],

            'nodes': data['nodes'],
        })
    }
    for rel in relations:
        presence_send(rel, out)
