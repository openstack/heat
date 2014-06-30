Nova Flavor plugin for OpenStack Heat
=====================================

This plugin enables using Nova Flavors as resources in a Heat template.

Note that the current implementation of the Nova Flavor resource does not
allow specifying the name and flavorid properties for the resource.
This is done to avoid potential naming collision upon flavor creation as
all flavor have a global scope.

### 1. Install the Nova Flavor plugin in Heat

NOTE: These instructions assume the value of heat.conf plugin_dirs includes the
default directory /usr/lib/heat.

To install the plugin, from this directory run:
    sudo python ./setup.py install

### 2. Restart heat

Only the process "heat-engine" needs to be restarted to load the new installed
plugin.

### Template Format

Here's an example nova flavor resource:
```yaml
heat_template_version: 2013-05-23
description:  Heat Flavor creation example
resources:
  test_flavor:
    type: OS::Nova::Flavor
    properties:
      ram: 1024
      vcpus: 1
      disk: 20
      swap: 2
      extra_specs: {"quota:disk_read_bytes_sec": "10240000"}
```

### Issues with the Nova Flavor plugin

By default only the admin tenant can manage flavors because of the default
policy in Nova: ```"compute_extension:flavormanage": "rule:admin_api"```

To let the possibility to all tenants to create flavors, the rule must be
replaced with the following: ```"compute_extension:flavormanage": ""```

The following error occurs if the policy has not been correctly set:
 ERROR: Policy doesn't allow compute_extension:flavormanage to be performed.

Currently all nova flavors have a global scope, which leads to several issues:
1. Per-stack flavor creation will pollute the global flavor list.
2. If two stacks create a flavor with the same name collision will occur,
which will lead to the following error:

 ERROR (Conflict): Flavor with name dupflavor already exists.

