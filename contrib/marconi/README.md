Marconi plugin for OpenStack Heat
================================

This plugin enable using Marconi queuing service as a resource in a Heat template.


### 1. Install the Marconi plugin in Heat

NOTE: Heat scans several directories to find plugins. The list of directories
is specified in the configuration file "heat.conf" with the "plugin_dirs"
directive.

To install the Marconi plugin, one needs to first make sure the
python-marconiclient package is installed - pip install -r requirements.txt, and
copy the plugin folder, e.g. marconi to wherever plugin_dirs points to.


### 2. Restart heat

Only the process "heat-engine" needs to be restarted to load the newly installed
plugin.
