Cinder volume_type plugin for OpenStack Heat
============================================

This plugin enables using Cinder volume_types as resources in a Heat template.


### 1. Install the Cinder volume_type plugin in Heat

NOTE: These instructions assume the value of heat.conf plugin_dirs includes the
default directory /usr/lib/heat.

To install the plugin, from this directory run:
    sudo python ./setup.py install

### 2. Restart heat

Only the process "heat-engine" needs to be restarted to load the new installed
plugin.

### Template Format

Here's an example cinder volume_type and cinder volume resources:
```yaml
heat_template_version: 2013-05-23
description:  Heat Cinder creation with volume_type example
resources:
  my_volume_type:
    type: OS::Cinder::VolumeType
    properties:
      name: volumeBackend
      metadata: {volume_backend_name: lvmdriver}
  my_volume:
    type: OS::Cinder::Volume
    properties:
      size: 1
      volume_type: {get_resource: my_volume_type}
```

### Issues with the Cinder volume_type plugin

By default only users who have the admin role can manage volume
types because of the default policy in
Cinder: ```"volume_extension:types_manage": "rule:admin_api"```

To let the possibility to all users to create volume type, the rule must be
replaced with the following: ```"volume_extension:types_manage": ""```

The following error occurs if the policy has not been correctly set:
 ERROR: Policy doesn't allow volume_extension:types_manage to be performed.