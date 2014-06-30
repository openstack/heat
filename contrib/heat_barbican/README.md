Barbican plugin for OpenStack Heat
================================

This plugin enables using Barbican resources in a Heat template.


### 1. Install the Barbican plugin in Heat

NOTE: These instructions assume the value of heat.conf plugin_dirs includes the
default directory /usr/lib/heat.

To install the plugin, from this directory run:
    sudo python ./setup.py install

### 2. Restart heat

Only the process "heat-engine" needs to be restarted to load the newly installed
plugin.
