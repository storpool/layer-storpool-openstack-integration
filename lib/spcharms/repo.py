"""
A StorPool Juju charm helper module for keeping track of Ubuntu packages that
have been installed by this unit.
"""
import fcntl
import json
import os
import re
import subprocess

from charmhelpers.core import hookenv


class StorPoolRepoException(Exception):
    """
    Indicate spcharms.repo errors; no additional error information.
    """
    pass


re_policy = {
    'installed': re.compile('\s* Installed: \s+ (?P<version> \S+ ) \s* $',
                            re.X),
    'candidate': re.compile('\s* Candidate: \s+ (?P<version> \S+ ) \s* $',
                            re.X),
}


def apt_pkg_policy(names):
    """
    Extract the "currently installed version" and "candidate version" fields
    from the `apt-cache policy` output for the specified package.
    """
    res = {}
    for pkg in names:
        pres = {}
        bad = False
        pb = subprocess.check_output(['apt-cache', 'policy', '--', pkg])
        for line in pb.decode().split('\n'):
            for pol in re_policy:
                m = re_policy[pol].match(line)
                if not m:
                    continue
                if pol in pres:
                    bad = True
                    break
                pres[pol] = m.groupdict()['version']
            if bad:
                break

        for pol in re_policy:
            if pol not in pres:
                bad = True
                break
            elif pres[pol] == '(none)':
                pres[pol] = None

        if bad:
            res[pkg] = None
        else:
            res[pkg] = pres

    return res


def pkgs_to_install(requested, policy):
    """
    Return a list of packages that actually need to be installed (not installed
    at all or different versions).
    """
    to_install = []

    for p in policy:
        ver = policy[p]
        if ver is None:
            return ('could not obtain APT policy information about '
                    'the {pkg} package'.format(pkg=p),
                    None)

        req = requested[p]
        if ver['installed'] is not None and \
           (req == '*' or req == ver['installed']):
            continue
        elif ver['candidate'] is None:
            return ('the {pkg} package is not available in the repositories, '
                    'cannot proceed'.format(pkg=p),
                    None)
        elif req != '*' and req != ver['candidate']:
            return ('the {req} version of the {pkg} package is not available '
                    'in the repositories, we have {cand} instead'
                    .format(req=req, pkg=p, cand=ver['candidate']),
                    None)

        to_install.append(p)

    return (None, to_install)


def apt_install(pkgs):
    """
    Install the specified packages and return a list of all the packages that
    were installed or upgraded along with them.
    """
    previous_b = subprocess.check_output([
        'dpkg-query', '-W', '--showformat',
        '${Package}\t${Version}\t${Status}\n'
    ])
    previous = dict(map(
        lambda d: (d[0], d[1]),
        filter(
            lambda d: len(d) == 3 and d[2].startswith('install'),
            map(
                lambda s: s.split('\t'),
                previous_b.decode().split('\n')
            )
        )
    ))

    cmd = ['apt-get', 'install', '-y', '--no-install-recommends', '--']
    cmd.extend(pkgs)
    subprocess.check_call(cmd)

    current_b = subprocess.check_output([
        'dpkg-query', '-W', '--showformat',
        '${Package}\t${Version}\t${Status}\n'
    ])
    current = dict(map(
        lambda d: (d[0], d[1]),
        filter(
            lambda d: len(d) == 3 and d[2].startswith('install'),
            map(
                lambda s: s.split('\t'),
                current_b.decode().split('\n')
            )
        )
    ))

    newly_installed = list(filter(
        lambda name: name not in previous or previous[name] != current[name],
        current.keys()
    ))
    return newly_installed


def install_packages(requested):
    """
    If any of the specified packages actually need to be installed, do that and
    return the list of installed ones (including dependencies).
    """
    try:
        policy = apt_pkg_policy(requested.keys())
    except Exception as e:
        return ('Could not query the APT policy for "{names}": {err}'
                .format(names=sorted(list(requested.keys())), err=e),
                None)

    (err, to_install) = pkgs_to_install(requested, policy)
    if err is not None:
        return (err, None)

    try:
        return (None, apt_install(to_install))
    except Exception as e:
        return ('Could not install the "{names}" packages: {e}'
                .format(names=sorted(to_install), e=e),
                None)


def charm_install_list_file():
    """
    Return the name of the file used for keeping track of installed packages.
    """
    return '/var/lib/storpool/install-charms.json'

# The part of the data structure that we care about:
# {
#   'charms': {
#     '<charm_name>': {
#       'layers': {
#         '<layer_name>': {
#           'packages': ['p1', 'p2', ...]
#         }
#     }
#   },
#
#   'packages': {
#     'remove': ['p3', 'p4', ...]
#   }
# }


def record_packages(layer_name, names, charm_name=None):
    """
    Record the list of packages installed by the current unit's layer.
    """
    if charm_name is None:
        charm_name = hookenv.charm_name()

    if not os.path.isdir('/var/lib/storpool'):
        os.mkdir('/var/lib/storpool', mode=0o700)
    with open(charm_install_list_file(), mode='at'):
        # Just making sure the file exists so we can open it as r+t.
        pass
    with open(charm_install_list_file(), mode='r+t') as listf:
        fcntl.lockf(listf, fcntl.LOCK_EX)

        # OK, we're ready to go now
        contents = listf.read()
        if len(contents) > 0:
            data = json.loads(contents)
        else:
            data = {'charms': {}}

        if charm_name not in data['charms']:
            data['charms'][charm_name] = {'layers': {}}
        layers = data['charms'][charm_name]['layers']

        if layer_name not in layers:
            layers[layer_name] = {'packages': []}
        layer = layers[layer_name]

        pset = set(layer['packages'])
        cset = set.union(pset, set(names))
        layer['packages'] = list(sorted(cset))

        # Hm, any packages that no longer need to be uninstalled?
        if 'packages' not in data:
            data['packages'] = {'remove': []}
        data['packages']['remove'] = \
            list(sorted(set(data['packages']['remove']).difference(cset)))

        # Right, so let's write it back
        listf.seek(0)
        print(json.dumps(data), file=listf)
        listf.truncate()


def unrecord_packages(layer_name, charm_name=None):
    """
    Remove the packages installed by the specified unit's layer from
    the record.
    Uninstall those of them are not wanted by any other unit's layer.
    """
    if charm_name is None:
        charm_name = hookenv.charm_name()

    try:
        with open(charm_install_list_file(), mode='r+t') as listf:
            fcntl.lockf(listf, fcntl.LOCK_EX)

            # ...and it must contain valid JSON?
            data = json.loads(listf.read())

            packages = set()
            has_layer = False
            has_charm = charm_name in data['charms']
            changed = False
            if has_charm:
                layers = data['charms'][charm_name]['layers']
                has_layer = layer_name in layers
                if has_layer:
                    layer = layers[layer_name]
                    packages = set(layer['packages'])
                    del layers[layer_name]
                    changed = True
                    if not layers:
                        del data['charms'][charm_name]

            # Right, so let's write it back if needed
            if changed:
                listf.seek(0)
                print(json.dumps(data), file=listf)
                listf.truncate()

            changed = False
            if 'packages' not in data:
                data['packages'] = {'remove': []}
            try_remove = set(data['packages']['remove']).union(packages)
            for cdata in data['charms'].values():
                for layer in cdata['layers'].values():
                    try_remove = try_remove.difference(set(layer['packages']))
            if try_remove != set(data['packages']['remove']):
                changed = True

            removed = set()
            while True:
                removed_now = set()

                # Sigh... don't we just love special cases...
                pkgs = set(['libwww-perl', 'liblwp-protocol-https-perl'])
                if pkgs.issubset(try_remove):
                    if subprocess.call(['dpkg', '-r', '--dry-run', '--'] +
                                       list(pkgs),
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE) == 0:
                        subprocess.call(['dpkg', '--purge', '--'] + list(pkgs))
                        removed_now = removed_now.union(pkgs)
                        changed = True

                # Now go for them all
                for pkg in try_remove:
                    if subprocess.call(['dpkg', '-r', '--dry-run', '--', pkg],
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE) != 0:
                        continue
                    subprocess.call(['dpkg', '--purge', '--', pkg])
                    removed_now.add(pkg)
                    changed = True

                if removed_now:
                    removed = removed.union(removed_now)
                    try_remove = try_remove.difference(removed_now)
                else:
                    break
            data['packages']['remove'] = \
                list(sorted(try_remove.difference(removed)))

            # Let's write it back again if needed
            if changed:
                listf.seek(0)
                print(json.dumps(data), file=listf)
                listf.truncate()
    except FileNotFoundError:
        pass


def list_package_files(name):
    """
    List the files installed by the specified package.
    """
    files_b = subprocess.check_output(['dpkg', '-L', '--', name])
    return sorted(filter(
        lambda s: len(s) > 0,
        files_b.decode().split('\n')
    ))
