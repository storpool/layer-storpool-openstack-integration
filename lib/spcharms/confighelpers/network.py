"""
A StorPool Juju charm helper module for parsing and updating the Ubuntu
network interface configuration if needed.
"""
import glob
import os
import tempfile
import yaml

from spcharms import error as sperror
from spcharms import netplan as spnetplan
from spcharms import txn
from spcharms import utils as sputils

vlandef = [
    'post-up /sbin/ip link set dev {IF_VLAN_RAW_DEVICE} mtu {MTU}',
    'post-up /sbin/ip link set dev {IFACE} mtu {MTU}',
]
nonvlandef = [
    'post-up /sbin/ip link set dev {IFACE} mtu {MTU}',
    'post-up /sbin/ethtool -A {IFACE} autoneg off tx off rx on || true',
    'post-up /sbin/ethtool -C {IFACE} rx-usecs 16 || true',
    'post-up /sbin/ethtool -G {IFACE} rx 4096 tx 512 || true',
]


def rdebug(s, cond=None):
    """
    Pass the diagnostic message string `s` to the central diagnostic logger.
    """
    sputils.rdebug(s, prefix='config', cond=cond)


def fixup_interfaces_file(fname, data, handled):
    """
    Read an /etc/network/interfaces-like file, look for the interfaces
    listed in the `data` dictionary.  If any of them are found, check that
    they have all of the lines defined in the dictionary; otherwise add
    the missing lines.

    If the file contains a "source" or "source-directory" directive, process
    the specified files recursively.
    """
    if fname in handled:
        return
    rdebug('Trying to add interface data to {fname}'.format(fname=fname),
           cond='fixup-ifaces')
    handled.add(fname)

    def is_new_stanza(s):
        """
        Check if a line starting with the `s` word actually starts a new
        stanza in an /etc/network/interfaces-like file.
        """
        if s in ('iface', 'mapping', 'auto', 'source', 'source-directory'):
            return True
        return s.startswith('allow-')

    basedir = os.path.dirname(fname)
    in_iface = ''
    left = []
    with open(fname, mode='r') as f:
        with tempfile.NamedTemporaryFile(dir=basedir,
                                         mode='w+t',
                                         delete=True) as tempf:
            updated = False

            while True:
                ln = f.readline()
                if not ln:
                    break
                stripped = ln.strip()
                words = stripped.split()
                if not words:
                    print(ln, file=tempf, end='')
                    continue

                if in_iface:
                    if is_new_stanza(words[0]):
                        for missing in left:
                            print(missing, file=tempf)
                            updated = True
                        in_iface = False
                    else:
                        left = list(filter(lambda s: s != stripped, left))

                print(ln, file=tempf, end='')

                # A separate conditional, since we may fall through.
                if not in_iface and len(words) > 1:
                    if words[0] == 'iface' and words[1] in data:
                        in_iface = words[1]
                        left = data[in_iface]
                    elif words[0] == 'source':
                        for new_fname in filter(lambda s: os.path.isfile(s),
                                                glob.glob(words[1])):
                            fixup_interfaces_file(new_fname, data, handled)
                    elif words[0] == 'source-directory':
                        for new_fname in filter(lambda s: os.path.isfile(s),
                                                glob.glob(words[1] + '/*')):
                            fixup_interfaces_file(new_fname, data, handled)

            if in_iface:
                for missing in left:
                    print(missing, file=tempf)
                    updated = True

            if updated:
                rdebug('Updating {fname}'.format(fname=fname))
                tempf.flush()
                txn.install(tempf.name, fname, exact=True)
            else:
                rdebug('No need to update {fname}'.format(fname=fname),
                       cond='fixup-ifaces')

    rdebug('Done adding interface data to {fname}'.format(fname=fname),
           cond='fixup-ifaces')


def fixup_interfaces_netplan(fname, data):
    """
    Explicitly set the MTU on all the relevant interfaces in
    a netplan configuration file.
    """
    np = spnetplan.get_related(ifaces=list(data.keys()),
                               exclude=[os.path.basename(fname)])
    rdebug('Netplan configuration: {np}'.format(np=np),
           cond='fixup-ifaces')

    npdata = {}
    for name, cfg in data.items():
        mtu = cfg.get('MTU')
        if mtu is None:
            continue

        if name not in np.data:
            raise sperror.StorPoolException(
              'No {iface} in the netplan config'.format(iface=name))
        t = np.data[name].section

        if t not in npdata:
            npdata[t] = {}
        npdata[t][name] = {
            'mtu': int(mtu),
        }

    npdata = {
        'network': {
            'version': 2,
            **npdata
        },
    }
    rdebug('netplan data: {np}'.format(np=npdata), cond='fixup-interfaces')

    with tempfile.NamedTemporaryFile(dir=os.path.dirname(fname),
                                     mode='w+t',
                                     delete=True) as tempf:
        print(yaml.dump(npdata), file=tempf, end='')
        tempf.flush()
        txn.install('-o', 'root', '-g', 'root', '-m', '644', tempf.name, fname)


def fixup_interfaces(ifaces):
    """
    Modify the system network configuration to add the post-up commands to
    the StorPool interfaces.
    """
    rdebug('fixup_interfaces invoked for {ifaces}'.format(ifaces=ifaces),
           cond='fixup-ifaces')

    # Parse the interface names
    cfg = {}
    data = {}
    for iface_data in ifaces.split(','):
        parts = iface_data.split('=', 1)
        iface = parts[0]
        if len(parts) == 2:
            mtu = parts[1]
        else:
            mtu = '9000'

        parts = iface.split('.', 1)
        if len(parts) == 2:
            vlan = True
            parent = parts[0]
        else:
            vlan = False
            parent = ''

        if vlan:
            subst = {
                'IFACE': iface,
                'MTU': mtu,
                'IF_VLAN_RAW_DEVICE': parent,
            }
            cfg[iface] = subst
            data[iface] = list(map(lambda s: s.format(**subst), vlandef))
            subst = {
                'IFACE': parent,
                'MTU': mtu,
            }
            cfg[parent] = subst
            data[parent] = list(map(lambda s: s.format(**subst), nonvlandef))
        else:
            subst = {
                'IFACE': iface,
                'MTU': mtu,
            }
            cfg[iface] = subst
            data[iface] = list(map(lambda s: s.format(**subst), nonvlandef))

    rdebug('Gone through the interfaces, got data: {data}'.format(data=data),
           cond='fixup-ifaces')

    if os.path.isdir('/etc/netplan') and \
       os.path.isfile('/lib/netplan/generate'):
        rdebug('About to generate the netplan MTU configuration',
               cond='fixup-ifaces')
        fixup_interfaces_netplan('/etc/netplan/99-storpool.yaml', cfg)
    else:
        rdebug('Now about to go through the system network configuration...',
               cond='fixup-ifaces')
        fixup_interfaces_file('/etc/network/interfaces', data, set())
