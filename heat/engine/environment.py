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

import itertools

from heat.openstack.common import log
from heat.common import exception


LOG = log.getLogger(__name__)


class ResourceInfo(object):
    """Base mapping of resource type to implementation."""

    def __new__(cls, registry, path, value, **kwargs):
        '''Create a new ResourceInfo of the appropriate class.'''

        if cls != ResourceInfo:
            # Call is already for a subclass, so pass it through
            return super(ResourceInfo, cls).__new__(cls)

        name = path[-1]
        if name.endswith(('.yaml', '.template')):
            # a template url for the resource "Type"
            return TemplateResourceInfo(registry, path, value)
        elif not isinstance(value, basestring):
            return ClassResourceInfo(registry, path, value)
        elif value.endswith(('.yaml', '.template')):
            # a registered template
            return TemplateResourceInfo(registry, path, value)
        elif name.endswith('*'):
            return GlobResourceInfo(registry, path, value)
        else:
            return MapResourceInfo(registry, path, value)

    def __init__(self, registry, path, value):
        self.registry = registry
        self.path = path
        self.name = path[-1]
        self.value = value
        self.user_resource = True

    def __eq__(self, other):
        return (self.path == other.path and
                self.value == other.value and
                self.user_resource == other.user_resource)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        if self.user_resource != other.user_resource:
            # user resource must be sorted above system ones.
            return self.user_resource > other.user_resource
        if len(self.path) != len(other.path):
            # more specific (longer) path must be sorted above system ones.
            return len(self.path) > len(other.path)
        return self.path < other.path

    def __gt__(self, other):
        return other.__lt__(self)

    def get_resource_info(self, resource_type=None, resource_name=None):
        return self

    def matches(self, resource_type):
        return False

    def __str__(self):
        return '[%s](User:%s) %s -> %s' % (self.description,
                                           self.user_resource,
                                           self.name, str(self.value))


class ClassResourceInfo(ResourceInfo):
    """Store the mapping of resource name to python class implementation."""
    description = 'Plugin'

    def get_class(self):
        return self.value


class TemplateResourceInfo(ResourceInfo):
    """Store the info needed to start a TemplateResource.
    """
    description = 'Template'

    def __init__(self, registry, path, value):
        super(TemplateResourceInfo, self).__init__(registry, path, value)
        if self.name.endswith(('.yaml', '.template')):
            self.template_name = self.name
        else:
            self.template_name = value

    def get_class(self):
        from heat.engine.resources import template_resource
        return template_resource.TemplateResource


class MapResourceInfo(ResourceInfo):
    """Store the mapping of one resource type to another.
    like: OS::Networking::FloatingIp -> OS::Neutron::FloatingIp
    """
    description = 'Mapping'

    def get_class(self):
        return None

    def get_resource_info(self, resource_type=None, resource_name=None):
        return self.registry.get_resource_info(self.value, resource_name)


class GlobResourceInfo(MapResourceInfo):
    """Store the mapping (with wild cards) of one resource type to another.
    like: OS::Networking::* -> OS::Neutron::*
    """
    description = 'Wildcard Mapping'

    def get_resource_info(self, resource_type=None, resource_name=None):
        orig_prefix = self.name[:-1]
        new_type = self.value[:-1] + resource_type[len(orig_prefix):]
        return self.registry.get_resource_info(new_type, resource_name)

    def matches(self, resource_type):
        return resource_type.startswith(self.name[:-1])


class ResourceRegistry(object):
    """By looking at the environment, find the resource implementation."""

    def __init__(self, global_registry):
        self._registry = {'resources': {}}
        self.global_registry = global_registry

    def load(self, json_snippet):
        self._load_registry([], json_snippet)

    def register_class(self, resource_type, resource_class):
        ri = ResourceInfo(self, [resource_type], resource_class)
        self._register_info([resource_type], ri)

    def _load_registry(self, path, registry):
        for k, v in iter(registry.items()):
            if isinstance(v, dict):
                self._load_registry(path + [k], v)
            else:
                self._register_info(path + [k],
                                    ResourceInfo(self, path + [k], v))

    def _register_info(self, path, info):
        """place the new info in the correct location in the registry.
        path: a list of keys ['resources', 'my_server', 'OS::Compute::Server']
        """
        descriptive_path = '/'.join(path)
        name = path[-1]
        # create the structure if needed
        registry = self._registry
        for key in path[:-1]:
            if key not in registry:
                registry[key] = {}
            registry = registry[key]

        if name in registry and isinstance(registry[name], ResourceInfo):
            details = {
                'path': descriptive_path,
                'was': str(registry[name].value),
                'now': str(info.value)}
            LOG.warn(_('Changing %(path)s from %(was)s to %(now)s') % details)
        else:
            LOG.info(_('Registering %(path)s -> %(value)s') % {
                'path': descriptive_path,
                'value': str(info.value)})
        info.user_resource = (self.global_registry is not None)
        registry[name] = info

    def iterable_by(self, resource_type, resource_name=None):
        if resource_type.endswith(('.yaml', '.template')):
            # resource with a Type == a template
            # we dynamically create an entry as it has not been registered.
            if resource_type not in self._registry:
                res = ResourceInfo(self, [resource_type], None)
                self._register_info([resource_type], res)
            yield self._registry[resource_type]

        # handle a specific resource mapping.
        if resource_name:
            impl = self._registry['resources'].get(resource_name)
            if impl and resource_type in impl:
                yield impl[resource_type]

        # handle: "OS::Compute::Server" -> "Rackspace::Compute::Server"
        impl = self._registry.get(resource_type)
        if impl:
            yield impl

        # handle: "OS::*" -> "Dreamhost::*"
        def is_a_glob(resource_type):
            return resource_type.endswith('*')
        globs = itertools.ifilter(is_a_glob, self._registry.keys())
        for glob in globs:
            if self._registry[glob].matches(resource_type):
                yield self._registry[glob]

    def get_resource_info(self, resource_type, resource_name=None,
                          registry_type=None):
        """Find possible matches to the resource type and name.
        chain the results from the global and user registry to find
        a match.
        """
        # use cases
        # 1) get the impl.
        #    - filter_by(res_type=X), sort_by(res_name=W, is_user=True)
        # 2) in TemplateResource we need to get both the
        #    TemplateClass and the ResourceClass
        #    - filter_by(res_type=X, impl_type=TemplateResourceInfo),
        #      sort_by(res_name=W, is_user=True)
        #    - filter_by(res_type=X, impl_type=ClassResourceInfo),
        #      sort_by(res_name=W, is_user=True)
        # 3) get_types() from the api
        #    - filter_by(is_user=False)
        # 4) as_dict() to write to the db
        #    - filter_by(is_user=True)
        if self.global_registry is not None:
            giter = self.global_registry.iterable_by(resource_type,
                                                     resource_name)
        else:
            giter = []

        matches = itertools.chain(self.iterable_by(resource_type,
                                                   resource_name),
                                  giter)

        for info in sorted(matches):
            match = info.get_resource_info(resource_type,
                                           resource_name)
            if registry_type is None or isinstance(match, registry_type):
                return match

    def get_class(self, resource_type, resource_name=None):
        info = self.get_resource_info(resource_type,
                                      resource_name=resource_name)
        if info is None:
            msg = "Unknown resource Type : %s" % resource_type
            raise exception.StackValidationFailed(message=msg)
        return info.get_class()

    def as_dict(self):
        """Return user resources in a dict format."""
        def _as_dict(level):
            tmp = {}
            for k, v in iter(level.items()):
                if isinstance(v, dict):
                    tmp[k] = _as_dict(v)
                elif v.user_resource:
                    tmp[k] = v.value
            return tmp

        return _as_dict(self._registry)

    def get_types(self):
        '''Return a list of valid resource types.'''
        def is_plugin(key):
            if isinstance(self._registry[key], ClassResourceInfo):
                return True
            return False
        return [k for k in self._registry if is_plugin(k)]


SECTIONS = (PARAMETERS, RESOURCE_REGISTRY) = \
           ('parameters', 'resource_registry')


class Environment(object):

    def __init__(self, env=None, user_env=True):
        """Create an Environment from a dict of varing format.
        1) old-school flat parameters
        2) or newer {resource_registry: bla, parameters: foo}

        :param env: the json environment
        :param user_env: boolean, if false then we manage python resources too.
        """
        if env is None:
            env = {}
        if user_env:
            from heat.engine import resources
            global_registry = resources.global_env().registry
        else:
            global_registry = None

        self.registry = ResourceRegistry(global_registry)
        self.registry.load(env.get(RESOURCE_REGISTRY, {}))

        if 'parameters' in env:
            self.params = env['parameters']
        else:
            self.params = dict((k, v) for (k, v) in env.iteritems()
                               if k != RESOURCE_REGISTRY)

    def load(self, env_snippet):
        self.registry.load(env_snippet.get(RESOURCE_REGISTRY, {}))
        self.params.update(env_snippet.get('parameters', {}))

    def user_env_as_dict(self):
        """Get the environment as a dict, ready for storing in the db."""
        return {RESOURCE_REGISTRY: self.registry.as_dict(),
                PARAMETERS: self.params}

    def register_class(self, resource_type, resource_class):
        self.registry.register_class(resource_type, resource_class)

    def get_class(self, resource_type, resource_name=None):
        return self.registry.get_class(resource_type, resource_name)

    def get_types(self):
        return self.registry.get_types()

    def get_resource_info(self, resource_type, resource_name=None,
                          registry_type=None):
        return self.registry.get_resource_info(resource_type, resource_name,
                                               registry_type)
