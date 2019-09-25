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

from spcharms import error as sperror
from spcharms import utils as sputils


class StorPoolRepoException(Exception):
    """
    Indicate spcharms.repo errors; no additional error information.
    """

    pass


re_policy = {
    "installed": re.compile(
        r"\s* Installed: \s+ (?P<version> \S+ ) \s* $", re.X
    ),
    "candidate": re.compile(
        r"\s* Candidate: \s+ (?P<version> \S+ ) \s* $", re.X
    ),
}


def rdebug(s, cond=None):
    sputils.rdebug(s, prefix="repo", cond=cond)


def apt_pkg_policy(names):
    """
    Extract the "currently installed version" and "candidate version" fields
    from the `apt-cache policy` output for the specified package.
    """
    res = {}
    for pkg in names:
        pres = {}
        bad = False
        pb = subprocess.check_output(["apt-cache", "policy", "--", pkg])
        for line in pb.decode().split("\n"):
            for pol in re_policy:
                m = re_policy[pol].match(line)
                if not m:
                    continue
                if pol in pres:
                    bad = True
                    break
                pres[pol] = m.groupdict()["version"]
            if bad:
                break

        for pol in re_policy:
            if pol not in pres:
                bad = True
                break
            elif pres[pol] == "(none)":
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

    rdebug("Determining which packages to install/upgrade", cond="repo-which")
    spe = sperror.StorPoolPackageInstallException
    for p in policy:
        ver = policy[p]
        if ver is None:
            raise spe([p], "could not obtain APT policy information")

        req = requested[p]
        rdebug(
            "- {p}: requested {req} installed {inst} candidate {cand}".format(
                p=p, req=req, inst=ver["installed"], cand=ver["candidate"]
            ),
            cond="repo-which",
        )
        if ver["installed"] is not None and req == ver["installed"]:
            rdebug(
                "  - exact version requested, already installed",
                cond="repo-which",
            )
            continue
        elif ver["candidate"] is None:
            raise spe([p], "not available in the repositories")
        elif req == "*" and ver["candidate"] == ver["installed"]:
            rdebug("  - best candidate already installed", cond="repo-which")
            continue
        elif req != "*" and req != ver["candidate"]:
            raise spe(
                [p],
                "the {req} version is not available in "
                "the repositories, we have {cand} instead".format(
                    req=req, cand=ver["candidate"]
                ),
            )

        rdebug(
            "  - apparently we need to install or upgrade it",
            cond="repo-which",
        )
        to_install.append(p)

    rdebug(
        "We need to install/upgrade {ln} packages: {lst}".format(
            ln=len(to_install), lst=" ".join(sorted(to_install))
        )
    )
    return to_install


def apt_install(pkgs):
    """
    Install the specified packages and return a list of all the packages that
    were installed or upgraded along with them.
    """
    previous_b = subprocess.check_output(
        [
            "dpkg-query",
            "-W",
            "--showformat",
            "${Package}\t${Version}\t${Status}\n",
        ]
    )
    previous = dict(
        map(
            lambda d: (d[0], d[1]),
            filter(
                lambda d: len(d) == 3 and d[2].startswith("install"),
                map(lambda s: s.split("\t"), previous_b.decode().split("\n")),
            ),
        )
    )

    cmd = ["apt-get", "install", "-y", "--no-install-recommends", "--"]
    cmd.extend(pkgs)
    subprocess.check_call(cmd)

    current_b = subprocess.check_output(
        [
            "dpkg-query",
            "-W",
            "--showformat",
            "${Package}\t${Version}\t${Status}\n",
        ]
    )
    current = dict(
        map(
            lambda d: (d[0], d[1]),
            filter(
                lambda d: len(d) == 3 and d[2].startswith("install"),
                map(lambda s: s.split("\t"), current_b.decode().split("\n")),
            ),
        )
    )

    newly_installed = list(
        filter(
            lambda name: name not in previous
            or previous[name] != current[name],
            current.keys(),
        )
    )
    return newly_installed


def install_packages(requested):
    """
    If any of the specified packages actually need to be installed, do that and
    return the list of installed ones (including dependencies).
    """
    spe = sperror.StorPoolPackageInstallException
    try:
        policy = apt_pkg_policy(requested.keys())
    except Exception as e:
        raise spe(
            requested.keys(),
            "Could not query the APT policy: {err}".format(err=e),
        )

    to_install = pkgs_to_install(requested, policy)
    if to_install:
        try:
            return apt_install(to_install)
        except Exception as e:
            raise spe(requested.keys(), e)


def charm_install_list_file():
    """
    Return the name of the file used for keeping track of installed packages.
    """
    return "/var/lib/storpool/install-charms.json"


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

    if not os.path.isdir("/var/lib/storpool"):
        os.mkdir("/var/lib/storpool", mode=0o700)
    with open(charm_install_list_file(), mode="at"):
        # Just making sure the file exists so we can open it as r+t.
        pass
    with open(charm_install_list_file(), mode="r+t") as listf:
        fcntl.lockf(listf, fcntl.LOCK_EX)

        # OK, we're ready to go now
        contents = listf.read()
        if len(contents) > 0:
            data = json.loads(contents)
        else:
            data = {"charms": {}}

        if charm_name not in data["charms"]:
            data["charms"][charm_name] = {"layers": {}}
        layers = data["charms"][charm_name]["layers"]

        if layer_name not in layers:
            layers[layer_name] = {"packages": []}
        layer = layers[layer_name]

        pset = set(layer["packages"])
        cset = set.union(pset, set(names))
        layer["packages"] = list(sorted(cset))

        # Hm, any packages that no longer need to be uninstalled?
        if "packages" not in data:
            data["packages"] = {"remove": []}
        data["packages"]["remove"] = list(
            sorted(set(data["packages"]["remove"]).difference(cset))
        )

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
        with open(charm_install_list_file(), mode="r+t") as listf:
            fcntl.lockf(listf, fcntl.LOCK_EX)

            # ...and it must contain valid JSON?
            data = json.loads(listf.read())

            packages = set()
            has_layer = False
            has_charm = charm_name in data["charms"]
            changed = False
            if has_charm:
                layers = data["charms"][charm_name]["layers"]
                has_layer = layer_name in layers
                if has_layer:
                    layer = layers[layer_name]
                    packages = set(layer["packages"])
                    del layers[layer_name]
                    changed = True
                    if not layers:
                        del data["charms"][charm_name]

            # Right, so let's write it back if needed
            if changed:
                listf.seek(0)
                print(json.dumps(data), file=listf)
                listf.truncate()

            changed = False
            if "packages" not in data:
                data["packages"] = {"remove": []}
            try_remove = set(data["packages"]["remove"]).union(packages)
            for cdata in data["charms"].values():
                for layer in cdata["layers"].values():
                    try_remove = try_remove.difference(set(layer["packages"]))
            if try_remove != set(data["packages"]["remove"]):
                changed = True

            removed = set()
            while True:
                removed_now = set()

                # Sigh... don't we just love special cases...
                pkgs = set(["libwww-perl", "liblwp-protocol-https-perl"])
                if pkgs.issubset(try_remove):
                    if (
                        subprocess.call(
                            ["dpkg", "-r", "--dry-run", "--"] + list(pkgs),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                        == 0
                    ):
                        subprocess.call(["dpkg", "--purge", "--"] + list(pkgs))
                        removed_now = removed_now.union(pkgs)
                        changed = True

                # Now go for them all
                for pkg in try_remove:
                    if (
                        subprocess.call(
                            ["dpkg", "-r", "--dry-run", "--", pkg],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                        != 0
                    ):
                        continue
                    subprocess.call(["dpkg", "--purge", "--", pkg])
                    removed_now.add(pkg)
                    changed = True

                if removed_now:
                    removed = removed.union(removed_now)
                    try_remove = try_remove.difference(removed_now)
                else:
                    break
            data["packages"]["remove"] = list(
                sorted(try_remove.difference(removed))
            )

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
    files_b = subprocess.check_output(["dpkg", "-L", "--", name])
    return sorted(filter(lambda s: len(s) > 0, files_b.decode().split("\n")))
