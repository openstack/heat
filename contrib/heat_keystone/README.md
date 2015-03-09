Keystone plugin for OpenStack Heat
==================================

This plugin enables Keystone resources in a Heat template for
following resources types:
- Keystone Role (OS::Keystone:Role)
- Keystone Project (OS::Keystone:Project)
- Keystone Group (OS::Keystone:Group)
- Keystone User (OS::Keystone:User)

And it provides Custom Constrains for following keystone entities
- Keystone role
- Keystone domain
- Keystone project
- Keystone group

### 1. Install the Keystone plugin in Heat

NOTE: These instructions assume the value of heat.conf plugin_dirs includes
the default directory /usr/lib/heat.

To install the plugin, from this directory run:
    sudo python ./setup.py install

### 2. Restart heat

Only the process "heat-engine" needs to be restarted to load the newly
installed plugin.
