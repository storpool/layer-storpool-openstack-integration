"""
A StorPool Juju charm helper module: miscellaneous utility functions.
"""
import os
import platform
import subprocess
import time

from charmhelpers.core import hookenv, unitdata

from spcharms import config as spconfig
from spcharms import error as sperror
from spcharms import kvdata
from spcharms import status as spstatus

rdebug_node = platform.node()


def rdebug(s, prefix="storpool", cond=None):
    """
    Log a diagnostic message through the charms model logger and also,
    if explicitly requested in the charm configuration, to a local file.
    """
    if cond is not None:
        cfg = hookenv.config().get("storpool_debug")
        if cfg is None or cfg != "ALL" and cond not in cfg.split(","):
            return

    global rdebug_node
    data = "[[{hostname}:{prefix}]] {s}".format(
        hostname=rdebug_node, prefix=prefix, s=s
    )
    hookenv.log(data, hookenv.DEBUG)

    config = hookenv.config()
    def_fname = "/dev/null"
    fname = (
        def_fname
        if config is None
        else config.get("storpool_charm_log_file", def_fname)
    )
    if fname != def_fname:
        with open(fname, "a") as f:
            data_ts = "{tm} {data}".format(tm=time.ctime(), data=data)
            print(data_ts, file=f)


def check_in_lxc():
    """
    Check whether we are currently running within an LXC/LXD container.
    """
    try:
        with open("/proc/1/environ", mode="r") as f:
            contents = f.read()
            return bool(
                list(
                    filter(
                        lambda s: s == "container=lxc", contents.split("\x00")
                    )
                )
            )
    except Exception:
        return False


def err(msg):
    """
    Log an error message and set the unit's status.
    """
    hookenv.log(msg, hookenv.ERROR)
    spstatus.set("error", msg)


def bypassed(name):
    """
    Check whether the administrator has explicitly specified that
    the installation should proceed despite some detected problems.
    """
    return name in hookenv.config().get("bypassed_checks", "").split(",")


def check_cgroups(service):
    """
    Check whether the use of cgroups is enabled in the StorPool configuration
    and, if it is, whether the cgroups defined for the specified service are
    set up on this node.
    """
    rdebug("Checking the cgroup config for {svc}".format(svc=service))
    if bypassed("use_cgroups"):
        hookenv.log(
            'The "use_cgroups" bypass is meant '
            "FOR DEVELOPMENT ONLY!  DO NOT run a StorPool cluster in "
            "production with it!",
            hookenv.WARNING,
        )
        rdebug("- cgroups bypassed altogether")
        return True

    spe = sperror.StorPoolNoCGroupsException
    cfg = spconfig.get_dict()
    use_cgroups = cfg.get("SP_USE_CGROUPS", "0").lower()
    if use_cgroups not in ("1", "y", "yes", "t", "true"):
        raise spe(
            "The SP_USE_CGROUPS setting is not enabled in "
            "the StorPool configuration (bypass: use_cgroups)"
        )
    var = "SP_{upper}_CGROUPS".format(upper=service.upper())
    cgstr = cfg.get(var, None)
    if cgstr is None:
        raise spe("No {var} in the StorPool configuration".format(var=var))
    rdebug(
        'About to examine the "{cg}" string for valid cgroups'.format(
            cg=cgstr
        ),
        cond="cgroup",
    )
    for cgdef in filter(lambda s: s != "-g", cgstr.strip().split()):
        rdebug("- parsing {d}".format(d=cgdef), cond="cgroup")
        comp = cgdef.split(":")
        if len(comp) != 2:
            raise spe(
                "Unexpected component in {var}: {comp}".format(
                    var=var, comp=cgdef
                )
            )
        path = "/sys/fs/cgroup/{tp}/{p}".format(tp=comp[0], p=comp[1])
        rdebug("  - checking for {path}".format(path=path), cond="cgroup")
        if not os.path.isdir(path):
            raise spe(
                "No {comp} group for the {svc} service".format(
                    comp=cgdef, svc=service
                )
            )

    rdebug(
        "- the cgroups for {svc} are set up".format(svc=service), cond="cgroup"
    )
    return True


def get_machine_id():
    """
    Get the Juju node ID from the environment; may return "None" if
    the environment settings are not as expected.
    """
    kv = unitdata.kv()
    val = kv.get(kvdata.KEY_MACHINE_ID, None)
    if val is None:
        env = hookenv.execution_environment()
        if "env" not in env:
            rdebug(
                'No "env" in the execution environment: {env}'.format(env=env)
            )
            val = ""
        elif "JUJU_MACHINE_ID" not in env["env"]:
            rdebug(
                "No JUJU_MACHINE_ID in the environment: {env}".format(
                    env=env["env"]
                )
            )
            val = ""
        else:
            val = env["env"]["JUJU_MACHINE_ID"]
        kv.set(kvdata.KEY_MACHINE_ID, val)

    return None if val == "" else val


def get_parent_node():
    """
    Figure out the Juju node ID of the bare metal node that
    we are running on or above.
    """
    kv = unitdata.kv()
    val = kv.get(kvdata.KEY_PARENT_NODE_ID, None)
    if val is None:
        sp_node = get_machine_id()
        parts = sp_node.split("/")
        if len(parts) == 1:
            val = sp_node
        elif len(parts) == 3 and parts[1] in ("lxd", "kvm"):
            val = parts[0]
        else:
            err(
                'Could not parse the Juju node name "{node}"'.format(
                    node=sp_node
                )
            )
            val = ""
        kv.set(kvdata.KEY_PARENT_NODE_ID, val)

    return None if val == "" else val


def exec(cmd):
    """
    Run an external command and return both its exit code and
    its output (to the standard output stream only).
    """
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    output = p.communicate()[0].decode()
    res = p.returncode
    return {"res": res, "out": output}


def check_systemd_service(name, in_lxc=False):
    """
    Check for a systemd service with the specified name.
    """
    service = "{name}.service".format(name=name)
    spstatus.npset(
        "maintenance",
        "checking for the {name} service".format(name=name),
    )
    if in_lxc or check_in_lxc():
        rdebug(
            "running in an LXC container, not checking for " + service,
            prefix=name,
        )
        return

    lines = (
        subprocess.check_output(
            ["systemctl", "show", "-p", "Type", service],
            shell=False,
        )
        .decode("UTF-8")
        .splitlines()
    )
    rdebug("got {lines}".format(lines=repr(lines)), prefix=name)
    if len(lines) != 1 or lines[0] not in ("Type=forking", "Type=simple"):
        raise sperror.StorPoolMissingComponentsException([service])
