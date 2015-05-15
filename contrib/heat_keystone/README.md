Keystone plugin for OpenStack heat
==================================

This plugin enables keystone resources in a heat template for
following resources types:
- Keystone role (OS::Keystone::Role)
- Keystone project (OS::Keystone::Project)
- Keystone group (OS::Keystone::Group)
- Keystone user (OS::Keystone::User)
- Keystone service (OS::Keystone::Service)
- Keystone endpoint (OS::Keystone::Endpoint)

And it provides custom constrains for following keystone entities
- Keystone role
- Keystone domain
- Keystone project
- Keystone group
- Keystone service

NOTE: It supports only keystone v3 version

### 1. Install the keystone plugin in heat

NOTE: These instructions assume the value of heat.conf plugin_dirs includes
the default directory /usr/lib/heat.

To install the plugin, from this directory run:
    sudo python ./setup.py install

### 2. Restart heat

Only the process "heat-engine" needs to be restarted to load the newly
installed plugin.
