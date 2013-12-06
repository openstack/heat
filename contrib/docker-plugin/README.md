Docker plugin for OpenStack Heat
================================

This plugin enable using Docker containers as resources in a Heat template.


### 1. Install the Docker plugin in Heat

NOTE: Heat scans several directories to find plugins. The list of directories
is specified in the configuration file "heat.conf" with the "plugin_dirs"
directive.

Running the following commands will install the Docker plugin in an existing
Heat setup.

```
pip install -r requirements.txt
ln -sf $(cd heat/contrib/docker-plugin/plugin; pwd) /usr/lib/heat/docker
echo "plugin_dirs=$(cd heat/contrib/docker-plugin/plugin; pwd)" > /etc/heat/heat.conf
```

NOTE: If you already have plugins enabled, you should not run the last command
and instead edit the config file "/etc/heat/heat.conf" manually.


### 2. Restart heat

Only the process "heat-engine" needs to be restarted to load the new installed
plugin.
