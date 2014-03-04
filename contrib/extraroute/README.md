ExtraRoute plugin for OpenStack Heat
====================================

This plugin enables using ExtraRoute as a resource in a Heat template.

This resource allows assigning extra routes to Neutron routers via Heat
templates.

NOTE: Implementing ExtraRoute in the main heat tree is under discussion in the
heat community.

This plugin has been implemented in contrib to provide access to the
functionality while the discussion takes place, as some users have an immediate
requirement for it.
It may be moved to the main heat tree in due-course, depending on the outcome
of the community discussion.

### 1. Install the ExtraRoute plugin in Heat

NOTE: Heat scans several directories to find plugins. The list of directories
is specified in the configuration file "heat.conf" with the "plugin_dirs"
directive.

### 2. Restart heat

Only the process "heat-engine" needs to be restarted to load the newly
installed plugin.

### 3. Example of ExtraRoute

"router_extraroute": {
  "Type": "OS::Neutron::ExtraRoute",
  "Properties": {
    "router_id": { "Ref" : "router" },
    "destination": "172.16.0.0/24",
    "nexthop": "192.168.0.254"
  }
}
