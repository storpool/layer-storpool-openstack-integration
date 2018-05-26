"""
A StorPool Juju charm helper module for keeping track of changes made to
local files, esp. configuration files, using the txn-install(1) tool.
"""
import json
import os
import subprocess

from charmhelpers.core import hookenv

from spcharms import repo as sprepo


def module_name():
    """
    Use the charm name as a base for the module name passed to txn-install.
    """
    return 'charm-' + hookenv.charm_name()


def install(*args, exact=False, prefix=''):
    """
    Run txn-install for a single file.
    """
    cmd = ['env', 'TXN_INSTALL_MODULE=' + module_name(),
           'txn', 'install-exact' if exact else 'install']
    cmd.extend(args)
    cmd[-1] = prefix + cmd[-1]
    subprocess.check_call(cmd)


def list_modules():
    """
    Get the list of modules that have recorded changes through txn-install.
    """
    modules = subprocess.getoutput('txn list-modules')
    if modules is None:
        return []
    else:
        return modules.split('\n')


def rollback_if_needed():
    """
    Run `txn-install rollback` if necessary.
    """
    if module_name() in list_modules():
        subprocess.call(['txn', 'rollback', module_name()])


class Txn(object):
    """
    Encapsulate the use of txn-install for modifying files within a specified
    directory tree.
    """
    def __init__(self, prefix=''):
        """
        Initialize a Txn object with the specified directory tree prefix.
        """
        self.prefix = prefix

    def install(self, *args, exact=False):
        """
        Install a single file within the tree.
        """
        install(*args, exact=exact, prefix=self.prefix)

    def install_exact(self, *args):
        """
        Install a single file within the tree exactly as the destination one.
        """
        self.install(*args, exact=True)


class LXD(object):
    """
    Encapsulate operations performed on the filesystems of LXD containers.
    """
    @classmethod
    def handle_lxc(klass):
        """
        Check whether the charm configuration specifies that LXD containers
        should be examined at all.
        """
        config = hookenv.config()
        if config is None:
            return False
        handle_lxc = config.get('handle_lxc', False)
        return handle_lxc if handle_lxc is not None else False

    @classmethod
    def list_all(klass):
        """
        List all the LXD containers running on the host if configured.
        """
        if not klass.handle_lxc():
            return []
        lxc_b = subprocess.check_output(['lxc', 'list', '--format=json'])
        lst = json.loads(lxc_b.decode())
        return map(lambda c: c['name'], lst)

    @classmethod
    def construct_all(klass):
        """
        Create LXD objects for all the containers that should be handled,
        including the root one (the bare metal node).
        """
        lst = [''] + list(klass.list_all())
        return map(lambda name: klass(name=name), lst)

    def __init__(self, name):
        """
        Initialize a single container data with its name and root directory.
        """
        self.name = name
        if name == '':
            self.prefix = ''
        else:
            self.prefix = \
                '/var/lib/lxd/containers/{name}/rootfs'.format(name=name)
        self.txn = Txn(prefix=self.prefix)

    def exec_with_output(self, cmd):
        """
        Run a command within the LXD container.
        """
        if self.name != '':
            cmd = ['lxc', 'exec', self.name, '--'] + cmd
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        output = p.communicate()[0].decode()
        res = p.returncode
        return {
                'res': res,
                'out': output,
               }

    def copy_packages(self, *pkgnames):
        """
        Copy the files from Ubuntu packages installed on bare metal to
        the conainer's filesystem.
        """
        if self.prefix == '':
            return
        for pkgname in pkgnames:
            for f in sprepo.list_package_files(pkgname):
                if os.path.isfile(f):
                    self.txn.install_exact(f, f)
                elif os.path.isdir(f):
                    os.makedirs(self.prefix + f, mode=0o755, exist_ok=True)

    def get_package_tree(self, pkgname):
        """
        Recursively list an installed package's dependencies.
        """
        if self.prefix == '':
            return []

        present = self.exec_with_output(['dpkg-query', '-W',
                                         '-f', '${Version}', '--', pkgname])
        if present['res'] == 0:
            return []

        deps = list(map(
            lambda s: s[:-4] if s.endswith(':any') else s,
            map(
                lambda s: s.strip(' ').split(' ', 1)[0],
                subprocess.check_output(
                    ['dpkg-query', '-W', '-f', '${Depends}', '--', pkgname]
                ).decode().split(',')
            )
        ))
        res = [pkgname]
        for dep in deps:
            res.extend(self.get_package_tree(dep))
        return res

    def copy_package_trees(self, *pkgnames):
        """
        Copy all the files from the specified packages and their dependencies
        into the container's filesystem.
        """
        for pkg in pkgnames:
            packages = self.get_package_tree(pkg)
            if packages:
                self.copy_packages(*packages)
