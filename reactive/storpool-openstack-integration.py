from __future__ import print_function

import pwd
import os
import tempfile
import time
import subprocess

from charmhelpers.core import templating

from charms import reactive
from charms.reactive import helpers as rhelpers
from charmhelpers.core import hookenv

from spcharms import repo as sprepo
from spcharms import txn

def rdebug(s):
	with open('/tmp/storpool-charms.log', 'a') as f:
		print('{tm} [openstack-integration] {s}'.format(tm=time.ctime(), s=s), file=f)

openstack_components = ['cinder', 'os_brick', 'nova']

@reactive.when('storpool-repo-add.available', 'storpool-common.config-written')
@reactive.when_not('storpool-osi.package-installed')
@reactive.when_not('storpool-osi.stopped')
def install_package():
	rdebug('the OpenStack integration repo has become available and the common packages have been configured')

	hookenv.status_set('maintenance', 'obtaining the requested StorPool version')
	spver = hookenv.config().get('storpool_version', None)
	if spver is None or spver == '':
		rdebug('no storpool_version key in the charm config yet')
		return

	hookenv.status_set('maintenance', 'installing the StorPool OpenStack packages')
	(err, newly_installed) = sprepo.install_packages({
		'storpool-block': spver,
		'python-storpool-spopenstack': spver,
		'storpool-openstack-integration': '1.2.0-1~1ubuntu1',
	})
	if err is not None:
		rdebug('oof, we could not install packages: {err}'.format(err=err))
		rdebug('removing the package-installed state')
		return

	if newly_installed:
		rdebug('it seems we managed to install some packages: {names}'.format(names=newly_installed))
		sprepo.record_packages(newly_installed)
	else:
		rdebug('it seems that all the packages were installed already')

	rdebug('setting the package-installed state')
	reactive.set_state('storpool-osi.package-installed')
	hookenv.status_set('maintenance', '')

@reactive.when('storpool-osi.package-installed')
@reactive.when_not('storpool-osi.installed-into-lxds')
@reactive.when_not('storpool-osi.stopped')
def enable_and_start():
	hookenv.status_set('maintenance', 'installing the OpenStack integration into the running containers')
	rdebug('installing into the running containers')

	for lxd in txn.LXD.construct_all():
		rdebug('- trying for "{name}"'.format(name=lxd.name))

		if lxd.name == '':
			rdebug('  - no need to copy packages into "{name}"'.format(name=lxd.name))
		else:
			rdebug('  - copying packages into "{name}"'.format(name=lxd.name))
			lxd.copy_package_trees('storpool-openstack-integration')

		rdebug('  - trying to detect OpenStack components in "{name}"'.format(name=lxd.name))
		global openstack_components
		for comp in openstack_components:
			res = lxd.exec_with_output(['sp-openstack', '--', 'detect', comp])
			if res['res'] != 0:
				rdebug('    - {comp} not found'.format(comp=comp))
				continue
			rdebug('    - {comp} FOUND!'.format(comp=comp))

			res = lxd.exec_with_output(['sp-openstack', '--', 'check', comp])
			if res['res'] == 0:
				rdebug('    - {comp} integration already there'.format(comp=comp))
				continue
			rdebug('    - {comp} MISSING integration'.format(comp=comp))

			if lxd.name == '':
				rdebug('    - no need to copy more packages into "{name}"'.format(name=lxd.name))
			else:
				rdebug('    - installing the rest of our packages into "{name}"'.format(name=lxd.name))
				lxd.copy_package_trees('txn-install', 'python-storpool-spopenstack')

			rdebug('    - running sp-openstack install {comp}'.format(comp=comp))
			res = lxd.exec_with_output(['sp-openstack', '-T', txn.module_name(), '--', 'install', comp])
			if res['res'] != 0:
				raise Exception('Could not install the StorPool OpenStack integration for {comp} in the "{name}" container'.format(comp=comp, name=lxd.name))

			rdebug('    - done with {comp}'.format(comp=comp))

		rdebug('  - done with "{name}"'.format(name=lxd.name))

	rdebug('done with the running containers')
	reactive.set_state('storpool-osi.installed-into-lxds')
	hookenv.status_set('maintenance', '')

@reactive.when('storpool-osi.installed-into-lxds')
@reactive.when_not('storpool-osi.package-installed')
@reactive.when_not('storpool-osi.stopped')
def restart():
	reactive.remove_state('storpool-osi.installed-into-lxds')

@reactive.when('storpool-osi.package-installed')
@reactive.when_not('storpool-common.config-written')
@reactive.when_not('storpool-osi.stopped')
def reinstall():
	reactive.remove_state('storpool-osi.package-installed')

def reset_states():
	rdebug('state reset requested')
	reactive.remove_state('storpool-osi.package-installed')
	reactive.remove_state('storpool-osi.installed-into-lxds')

@reactive.hook('upgrade-charm')
def remove_states_on_upgrade():
	rdebug('storpool-osi.upgrade-charm invoked')
	reset_states()

@reactive.when('storpool-osi.stop')
@reactive.when_not('storpool-osi.stopped')
def remove_leftovers():
	rdebug('storpool-osi.stop invoked')
	reactive.remove_state('storpool-osi.stop')

	if not rhelpers.is_state('storpool-osi.no-propagate-stop'):
		rdebug('letting storpool-common know')
		reactive.set_state('storpool-common.stop')
	else:
		rdebug('apparently someone else will/has let storpool-common know')

	reset_states()
	reactive.set_state('storpool-osi.stopped')
