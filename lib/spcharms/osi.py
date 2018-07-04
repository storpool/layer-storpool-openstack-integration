"""
A StorPool Juju charm helper module for keeping track of the Cinder container.
"""
import os
import re
import subprocess

from charmhelpers.core import unitdata

from spcharms import error as sperror
from spcharms import kvdata
from spcharms import utils as sputils


def rdebug(s, cond=None):
    sputils.rdebug(s, prefix='osi', cond=cond)


def lxd_cinder_name():
    """
    Get the previously cached name of the local Cinder LXD container.
    """
    return unitdata.kv().get(kvdata.KEY_LXD_NAME, default=None)


def check_spopenstack_processes(name):
    """
    Check the processes with the specified command name for
    the 'spopenstack' group.
    """
    rdebug('Getting process credentials for {name}'.format(name=name))
    spe = sperror.StorPoolException
    p = subprocess.Popen(['pgrep', '-x', '--ns', str(os.getpid()), '--', name],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    res = list(map(lambda s: s.decode(), p.communicate()))
    stat = p.wait()
    if res[1] != '':
        raise spe('Could not look for a "{name}" process: '
                  'pgrep exited with code {code}: {err}'
                  .format(name=name, code=stat, err=res[1]))
    elif stat == 1:
        return {}
    elif stat != 0:
        raise spe('Could not look for a "{name}" process: '
                  'pgrep exited with code {code}'
                  .format(name=name, code=stat))

    data = {}
    try:
        pids = map(int, res[0].strip().split('\n'))
    except ValueError:
        raise spe('Could not look for a "{name}" process: '
                  'pgrep returned unexpected output: {res}'
                  .format(name=name, res=repr(res[0])))
    ps_cmd = ['ps', '-h', '-o', 'pid,user,group,supgrp']
    re_line = re.compile(
        '(?P<pid> 0 | [1-9][0-9]*) \s+ '
        '(?P<u> \S+ ) \s+ '
        '(?P<g> \S+ ) \s+ '
        '(?P<supp> \S+ ) $',
        re.X)
    for pid in pids:
        rdebug('- examining pid {pid}'.format(pid=pid))
        cmd = ps_cmd + [str(pid)]
        rdebug('  - {cmd}'.format(cmd=cmd))
        p = subprocess.Popen(cmd,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        res = list(map(lambda s: s.decode(), p.communicate()))
        stat = p.wait()
        if res[1] != '':
            raise spe('Could not examine the {name} process {pid}: '
                      'ps exited with code {code}: {err}'
                      .format(name=name, pid=pid, code=stat, err=res[1]))
        elif stat != 0:
            raise spe('Could not examine the {name} process {pid}: '
                      'ps exited with code {code}'
                      .format(name=name, pid=pid, code=stat))

        lines = res[0].strip().split('\n')
        rdebug('  - {lines}'.format(lines=repr(lines)))
        if len(lines) == 0:
            rdebug('  - seems to have gone away')
            continue
        elif len(lines) > 1:
            raise spe('Could not examine the {name} process {pid}: '
                      'ps returned more than one line: {lines}'
                      .format(name=name, pid=pid, lines=repr(lines)))
        m = re_line.match(lines[0])
        if m is None:
            raise spe('Could not examine the {name} process {pid}: '
                      'ps returned a weird first line: {line}'
                      .format(name=name, pid=pid, line=repr(lines[0])))
        d = m.groupdict()
        if d['pid'] != str(pid):
            raise spe('Could not examine the {name} process {pid}: '
                      'ps returned a weird process ID: {line}'
                      .format(name=name, pid=pid, line=repr(lines[0])))

        all_groups = [d['g']] + d['supp'].split(',')
        data[pid] = 'spopenstack' in all_groups

    rdebug('Examined {name} processes: {d}'.format(name=name, d=data))
    return data
