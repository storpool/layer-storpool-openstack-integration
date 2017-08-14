from charmhelpers.core import unitdata

def lxd_cinder_name():
	return unitdata.kv().get('storpool-openstack-integration.lxd-name', default=None)
