# Heat resources for working with the Rackspace Cloud

The resources and configuration in this module are for using Heat with the Rackspace Cloud. These resources either
allow using Rackspace services that don't have equivalent services in OpenStack or account for differences between
a generic OpenStack deployment and Rackspace Cloud.

This package also includes a Keystone V2 compatible client plugin, that can be used in place of the default client
for clouds running older versions of Keystone.

## Installation

### 1. Install the Rackspace plugins in Heat

NOTE: These instructions assume the value of heat.conf plugin_dirs includes the
default directory /usr/lib/heat.

- To install the plugin, from this directory run:

        sudo python ./setup.py install

- (Optional) If you want to enable the Keystone V2 client plugin, set the `keystone_backend` option to

        `heat.engine.plugins.heat_keystoneclient_v2.client.KeystoneClientV2`

### 2. Restart heat

Only the process "heat-engine" needs to be restarted to load the newly installed
plugin.


## Resources
The following resources are provided for compatibility:

* `Rackspace::Cloud::Server`:
>Provide compatibility with `OS::Nova::Server` and allow for working `user_data` and `Metadata`. This is deprecated and should be replaced with `OS::Nova::Server` once service compatibility is implemented by Rackspace.

* `Rackspace::Cloud::LoadBalancer`:
>Use the Rackspace Cloud Loadbalancer service; not compatible with `OS::Neutron::LoadBalancer`.

### Usage
#### Templates
#### Configuration


## Heat Keystone V2

Note that some forward compatibility decisions had to be made for the Keystone V2 client plugin:

* Stack domain users are created as users on the stack owner's tenant
  rather than the stack's domain
* Trusts are not supported

### How it works

By setting the `keystone_backend` option, the KeystoneBackend class in
`heat/engine/clients/os/keystone/heat_keystoneclient.py` will instantiate the plugin
KeystoneClientV2 class and use that instead of the default client in
`heat/engine/clients/os/keystone/heat_keystoneclient.py`.
