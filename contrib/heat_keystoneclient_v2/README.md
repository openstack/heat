# Heat Keystone V2

This plugin is a Keystone V2 compatible client.  It can be used to
replace the default client for clouds running older versions of
Keystone.

Some forward compatibility decisions had to be made:

* Stack domain users are created as users on the stack owner's tenant
  rather than the stack's domain
* Trusts are not supported


# Installation

1. In `heat.conf`, add the path to the `heat_keystoneclient_v2` root
   directory to `plugin_dirs`.
   e.g.: `plugin_dirs=path/to/heat/contrib/heat_keystoneclient_v2`

2. Set the `keystone_backend` option to
   `heat.engine.plugins.heat_keystoneclient_v2.client.KeystoneClientV2`


# How it works

By setting the `keystone_backend` option, the KeystoneBackend class in
`heat/common/heat_keystoneclient.py` will instantiate the plugin
KeystoneClientV2 class and use that instead of the default client in
`heat/common/heat_keystoneclient.py`.
