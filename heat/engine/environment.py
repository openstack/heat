
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

import glob
import itertools
import os.path

from oslo.config import cfg

from heat.openstack.common import log
from heat.openstack.common.gettextutils import _
from heat.common import environment_format
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
        if other is None:
            return False
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
        self.value = self.template_name

    def get_class(self):
        from heat.engine.resources import template_resource
        return template_resource.generate_class(str(self.name),
                                                self.template_name)


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
            if v is None:
                self._register_info(path + [k], None)
            elif isinstance(v, dict):
                self._load_registry(path + [k], v)
            else:
                self._register_info(path + [k],
                                    ResourceInfo(self, path + [k], v))

    def _register_info(self, path, info):
        """place the new info in the correct location in the registry.
        path: a list of keys ['resources', 'my_server', 'OS::Nova::Server']
        """
        descriptive_path = '/'.join(path)
        name = path[-1]
        # create the structure if needed
        registry = self._registry
        for key in path[:-1]:
            if key not in registry:
                registry[key] = {}
            registry = registry[key]

        if info is None:
            if name.endswith('*'):
                # delete all matching entries.
                for res_name in registry.keys():
                    if isinstance(registry[res_name], ResourceInfo) and \
                       res_name.startswith(name[:-1]):
                        LOG.warn(_('Removing %(item)s from %(path)s') % {
                            'item': res_name,
                            'path': descriptive_path})
                        del registry[res_name]
            else:
                # delete this entry.
                LOG.warn(_('Removing %(item)s from %(path)s') % {
                    'item': name,
                    'path': descriptive_path})
                registry.pop(name, None)
            return

        if name in registry and isinstance(registry[name], ResourceInfo):
            if registry[name] == info:
                return
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
        is_templ_type = resource_type.endswith(('.yaml', '.template'))
        if self.global_registry is not None and is_templ_type:
            # we only support dynamic resource types in user environments
            # not the global environment.
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

        # handle: "OS::Nova::Server" -> "Rackspace::Cloud::Server"
        impl = self._registry.get(resource_type)
        if impl:
            yield impl

        # handle: "OS::*" -> "Dreamhost::*"
        def is_a_glob(resource_type):
            return resource_type.endswith('*')
        globs = itertools.ifilter(is_a_glob, self._registry.keys())
        for pattern in globs:
            if self._registry[pattern].matches(resource_type):
                yield self._registry[pattern]

    def get_resource_info(self, resource_type, resource_name=None,
                          registry_type=None, accept_fn=None):
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
            if ((registry_type is None or isinstance(match, registry_type)) and
                    (accept_fn is None or accept_fn(info))):
                return match

    def get_class(self, resource_type, resource_name=None, accept_fn=None):
        if resource_type == "":
            msg = _('Resource "%s" has no type') % resource_name
            raise exception.StackValidationFailed(message=msg)
        elif resource_type is None:
            msg = _('Non-empty resource type is required '
                    'for resource "%s"') % resource_name
            raise exception.StackValidationFailed(message=msg)
        elif not isinstance(resource_type, basestring):
            msg = _('Resource "%s" type is not a string') % resource_name
            raise exception.StackValidationFailed(message=msg)

        info = self.get_resource_info(resource_type,
                                      resource_name=resource_name,
                                      accept_fn=accept_fn)
        if info is None:
            msg = _("Unknown resource Type : %s") % resource_type
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

    def get_types(self, support_status):
        '''Return a list of valid resource types.'''

        def is_resource(key):
            return isinstance(self._registry[key], (ClassResourceInfo,
                                                    TemplateResourceInfo))

        def status_matches(cls):
            return (support_status is None or
                    cls.get_class().support_status.status ==
                    support_status.encode())

        return [name for name, cls in self._registry.iteritems()
                if is_resource(name) and status_matches(cls)]


SECTIONS = (PARAMETERS, RESOURCE_REGISTRY) = \
           ('parameters', 'resource_registry')


class Environment(object):

    def __init__(self, env=None, user_env=True):
        """Create an Environment from a dict of varying format.
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
        self.constraints = {}

    def load(self, env_snippet):
        self.registry.load(env_snippet.get(RESOURCE_REGISTRY, {}))
        self.params.update(env_snippet.get('parameters', {}))

    def user_env_as_dict(self):
        """Get the environment as a dict, ready for storing in the db."""
        return {RESOURCE_REGISTRY: self.registry.as_dict(),
                PARAMETERS: self.params}

    def register_class(self, resource_type, resource_class):
        self.registry.register_class(resource_type, resource_class)

    def register_constraint(self, constraint_name, constraint):
        self.constraints[constraint_name] = constraint

    def get_class(self, resource_type, resource_name=None):
        return self.registry.get_class(resource_type, resource_name)

    def get_types(self, support_status=None):
        return self.registry.get_types(support_status)

    def get_resource_info(self, resource_type, resource_name=None,
                          registry_type=None):
        return self.registry.get_resource_info(resource_type, resource_name,
                                               registry_type)

    def get_constraint(self, name):
        return self.constraints.get(name)


def read_global_environment(env, env_dir=None):
    if env_dir is None:
        cfg.CONF.import_opt('environment_dir', 'heat.common.config')
        env_dir = cfg.CONF.environment_dir

    try:
        env_files = glob.glob(os.path.join(env_dir, '*'))
    except OSError as osex:
        LOG.error(_('Failed to read %s') % env_dir)
        LOG.exception(osex)
        return

    for file_path in env_files:
        try:
            with open(file_path) as env_fd:
                LOG.info(_('Loading %s') % file_path)
                env_body = environment_format.parse(env_fd.read())
                environment_format.default_for_missing(env_body)
                env.load(env_body)
        except ValueError as vex:
            LOG.error(_('Failed to parse %(file_path)s') % {
                      'file_path': file_path})
            LOG.exception(vex)
        except IOError as ioex:
            LOG.error(_('Failed to read %(file_path)s') % {
                      'file_path': file_path})
            LOG.exception(ioex)
