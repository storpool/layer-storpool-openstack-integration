from __future__ import print_function

import os
import platform
import pwd
import re
import tempfile
import time
import subprocess

from charmhelpers.core import templating

from charms import reactive
from charms.reactive import helpers as rhelpers
from charmhelpers.core import hookenv, host, unitdata

from spcharms import repo as sprepo
from spcharms import txn

def block_conffile():
	return '/etc/storpool.conf.d/storpool-cinder-block.conf'

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
		sprepo.record_packages('storpool-osi', newly_installed)
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

	try:
		ourid_outb = subprocess.check_output(['storpool_showconf', '-e', '-n', 'SP_OURID'])
		ourid_lines = ourid_outb.decode().split('\n')
		if len(ourid_lines) != 2 or ourid_lines[1] != '' or not re.match('(?: 0 | [1-9][0-9]* ) $', ourid_lines[0], re.X):
			rdebug('- could not determine the StorPool SP_OURID setting, bailing out')
			return
		sp_ourid = ourid_lines[0]
	except Exception as e:
		rdebug('- could not run storpool_showconf to determine the StorPool SP_OURID setting: {e}'.format(e=e))
		return
	rdebug('- got SP_OURID {ourid}'.format(ourid=sp_ourid))

	lxd_cinder = None
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
			if comp == 'cinder' and lxd.name != '':
				if lxd_cinder is None:
					rdebug('     - and it is a Cinder one, stashing it...')
					lxd_cinder = lxd
					rdebug('    - and installing /etc/storpool.conf into "{name}"'.format(name=lxd.name))
					lxd.txn.install_exact('/etc/storpool.conf', '/etc/storpool.conf')
				else:
					rdebug('     - oof, found two Cinder LXDs, using "{first}" and not "{second}"'.format(first=lxd_cinder.name, second=lxd.name))

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
				rdebug('    - and installing /etc/storpool.conf into "{name}"'.format(name=lxd.name))
				lxd.txn.install_exact('/etc/storpool.conf', '/etc/storpool.conf')

				cfgdir = '/etc/storpool.conf.d'
				pfxdir = lxd.prefix + cfgdir
				if not os.path.isdir(pfxdir):
					rdebug('    - and creating the {pfxdir} directory'.format(pfxdir=pfxdir))
					os.mkdir(pfxdir, mode=0o755)
				cfgname = cfgdir + '/storpool-cinder-ourid.conf'
				rdebug('    - and generating the {cfgname} file in "{name}"'.format(cfgname=cfgname, name=lxd.name))
				with tempfile.NamedTemporaryFile(dir='/tmp', mode='w+t') as spouridconf:
					print('[{name}]\nSP_OURID={ourid}'.format(name=lxd.name, ourid=sp_ourid), file=spouridconf)
					spouridconf.flush()
					lxd.txn.install('-o', 'root', '-g', 'root', '-m', '644', '--', spouridconf.name, cfgname)

			rdebug('    - running sp-openstack install {comp}'.format(comp=comp))
			res = lxd.exec_with_output(['sp-openstack', '-T', txn.module_name(), '--', 'install', comp])
			if res['res'] != 0:
				raise Exception('Could not install the StorPool OpenStack integration for {comp} in the "{name}" container'.format(comp=comp, name=lxd.name))

			rdebug('    - done with {comp}'.format(comp=comp))

		rdebug('  - done with "{name}"'.format(name=lxd.name))

	rdebug('done with the running containers')

	confname = block_conffile()
	if lxd_cinder is not None:
		rdebug('found a Cinder container at "{name}"'.format(name=lxd_cinder.name))
		try:
			rdebug('about to record the name of the Cinder LXD - "{name}" - into {confname}'.format(name=lxd_cinder.name, confname=confname))
			dirname = os.path.dirname(confname)
			rdebug('- checking for the {dirname} directory'.format(dirname=dirname))
			if not os.path.isdir(dirname):
				rdebug('  - nah, creating it')
				os.mkdir(dirname, mode=0o755)

			rdebug('- is the file there?')
			okay = False
			expected_contents = [
				'[{node}]'.format(node=platform.node()),
				'SP_EXTRA_FS=lxd:{name}'.format(name=lxd_cinder.name)
			]
			if os.path.isfile(confname):
				rdebug('  - yes, it is... but does it contain the right data?')
				with open(confname, mode='r') as conffile:
					contents = list(map(lambda s: s.rstrip(), conffile.readlines()))
					if contents == expected_contents:
						rdebug('   - whee, it already does!')
						okay = True
					else:
						rdebug('   - it does NOT: {lst}'.format(lst=contents))
			else:
				rdebug('   - nah...')
				if os.path.exists(confname):
					rdebug('     - but it still exists?!')
					subprocess.call(['rm', '-rf', '--', confname])
					if os.path.exists(confname):
						rdebug('     - could not remove it, so leaving it alone, I guess')
						okay = True

			if not okay:
				rdebug('- about to recreate the {confname} file'.format(confname=confname))
				with tempfile.NamedTemporaryFile(dir='/tmp', mode='w+t') as spconf:
					print('\n'.join(expected_contents), file=spconf)
					txn.install('-o', 'root', '-g', 'root', '-m', '644', '--', spconf.name, confname)
				rdebug('- looks like we are done with it')
				rdebug('- let us try to restart the storpool_block service (it may not even have been started yet, so ignore errors)')
				try:
					if host.service_running('storpool_block'):
						rdebug('  - well, it does seem to be running, so restarting it')
						host.service_restart('storpool_block')
					else:
						rdebug('  - nah, it was not running at all indeed')
				except Exception as e:
					rdebug('  - could not restart the service, but ignoring the error: {e}'.format(e=e))
			unitdata.kv().set('storpool-openstack-integration.lxd-name', lxd_cinder.name)
		except Exception as e:
			rdebug('could not check for and/or recreate the {confname} storpool_block config file adapted the "{name}" LXD container: {e}'.format(confname=confname, name=lxd_cinder.name, e=e))
	else:
		rdebug('no Cinder LXD containers found, checking for any previously stored configuration...')
		removed = False
		if os.path.isfile(confname):
			rdebug('- yes, {confname} exists, removing it'.format(confname=confname))
			try:
				os.unlink(confname)
				removed = True
			except Exception as e:
				rdebug('could not remove {confname}: {e}'.format(confname=confname, e=e))
		elif os.path.exists(confname):
			rdebug('- well, {confname} exists, but it is not a file; removing it anyway'.format(confname=confname))
			subprocess.call(['rm', '-rf', '--', confname])
			removed = True
		if removed:
			rdebug('- let us try to restart the storpool_block service (it may not even have been started yet, so ignore errors)')
			try:
				if host.service_running('storpool_block'):
					rdebug('  - well, it does seem to be running, so restarting it')
					host.service_restart('storpool_block')
				else:
					rdebug('  - nah, it was not running at all indeed')
			except Exception as e:
				rdebug('  - could not restart the service, but ignoring the error: {e}'.format(e=e))

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

	rdebug('uninstalling any OpenStack-related StorPool packages')
	sprepo.unrecord_packages('storpool-osi')

	if not rhelpers.is_state('storpool-osi.no-propagate-stop'):
		rdebug('letting storpool-common know')
		reactive.set_state('storpool-common.stop')
	else:
		rdebug('apparently someone else will/has let storpool-common know')

	reset_states()
	reactive.set_state('storpool-osi.stopped')
