# vim: tabstop=4 shiftwidth=4 softtabstop=4

#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# The environment should look like this:
# Note: the base_url, urls and files should be handled earlier
#       and by the time it gets to the engine they are all just names.
#
# Use case 1: I want to use all the resource types from provider X
#resource_registry:
#  "OS::*": "Dreamhost::*"
#  # could also use a url like this (assuming they could all be
#  # expressed in nested stacks)
#  "OS::*": http://dreamhost.com/bla/resources-types/*"
#
# Use case 2: I want to use mostly the default resources except my
# custom one for a particular resource in the template.
#resource_registry:
#  resources:
#    my_db_server:
#      "OS::DBInstance": file://~/all_my_cool_templates/db.yaml
#
# Use case 3: I always want to always map resource type X to Y
#resource_registry:
#  "OS::Networking::FloatingIP": "OS::Nova::FloatingIP"
#  "OS::Loadbalancer": file://~/all_my_cool_templates/lb.yaml
#
# Use case 4: I use custom resources a lot and want to shorten the
# url/path
#resource_registry:
#  base_url: http://bla.foo/long/url/
#  resources:
#    my_db_server:
#      "OS::DBInstance": dbaas.yaml
#
# Use case 5: I want to put some common parameters in the environment
#parameters:
#  KeyName: heat_key
#  InstanceType: m1.large
#  DBUsername: wp_admin
#  LinuxDistribution: F17


class Environment(object):

    def __init__(self, env=None):
        """Create an Environment from a dict of varing format.
        1) old-school flat parameters
        2) or newer {resource_registry: bla, parameters: foo}

        :param env: the json environment
        """
        if env is None:
            env = {}
        self.resource_registry = env.get('resource_registry', {})
        if 'resources' not in self.resource_registry:
            self.resource_registry['resources'] = {}
        if 'parameters' in env:
            self.params = env['parameters']
        else:
            self.params = dict((k, v) for (k, v) in env.iteritems()
                               if k != 'resource_registry')

    def get_resource_type(self, resource_type, resource_name):
        """Get the specific resource type that the user wants to implement
        'resource_type'.
        """
        impl = self.resource_registry['resources'].get(resource_name)
        if impl and resource_type in impl:
            return impl[resource_type]

        # handle: "OS::Compute::Server" -> "Rackspace::Compute::Server"
        impl = self.resource_registry.get(resource_type)
        if impl:
            return impl
        # handle: "OS::*" -> "Dreamhost::*"
        for k, v in iter(self.resource_registry.items()):
            if k.endswith('*'):
                orig_prefix = k[:-1]
                if resource_type.startswith(orig_prefix):
                    return v[:-1] + resource_type[len(orig_prefix):]
        # no special handling, just return what we were given.
        return resource_type

    def user_env_as_dict(self):
        """Get the environment as a dict, ready for storing in the db."""
        return {'resource_registry': self.resource_registry,
                'parameters': self.params}
