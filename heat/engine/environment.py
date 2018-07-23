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

import collections
import glob
import itertools
import os.path
import re
import weakref

from oslo_config import cfg
from oslo_log import log
from oslo_utils import fnmatch
import six

from heat.common import environment_format as env_fmt
from heat.common import exception
from heat.common.i18n import _
from heat.common import policy
from heat.engine import support

LOG = log.getLogger(__name__)


HOOK_TYPES = (
    HOOK_PRE_CREATE, HOOK_PRE_UPDATE, HOOK_PRE_DELETE, HOOK_POST_CREATE,
    HOOK_POST_UPDATE, HOOK_POST_DELETE
) = (
    'pre-create', 'pre-update', 'pre-delete', 'post-create',
    'post-update', 'post-delete'
)

RESTRICTED_ACTIONS = (UPDATE, REPLACE) = ('update', 'replace')


def valid_hook_type(hook):
    return hook in HOOK_TYPES


def valid_restricted_actions(action):
    return action in RESTRICTED_ACTIONS


def is_hook_definition(key, value):
    is_valid_hook = False
    if key == 'hooks':
        if isinstance(value, six.string_types):
            is_valid_hook = valid_hook_type(value)
        elif isinstance(value, collections.Sequence):
            is_valid_hook = all(valid_hook_type(hook) for hook in value)

        if not is_valid_hook:
            msg = (_('Invalid hook type "%(value)s" for resource '
                     'breakpoint, acceptable hook types are: %(types)s') %
                   {'value': value, 'types': HOOK_TYPES})
            raise exception.InvalidBreakPointHook(message=msg)

    return is_valid_hook


def is_valid_restricted_action(key, value):
    valid_action = False
    if key == 'restricted_actions':
        if isinstance(value, six.string_types):
            valid_action = valid_restricted_actions(value)
        elif isinstance(value, collections.Sequence):
            valid_action = all(valid_restricted_actions(
                action) for action in value)

        if not valid_action:
            msg = (_('Invalid restricted_action type "%(value)s" for '
                     'resource, acceptable restricted_action '
                     'types are: %(types)s') %
                   {'value': value, 'types': RESTRICTED_ACTIONS})
            raise exception.InvalidRestrictedAction(message=msg)

    return valid_action


class ResourceInfo(object):
    """Base mapping of resource type to implementation."""

    def __new__(cls, registry, path, value):
        """Create a new ResourceInfo of the appropriate class."""

        if cls is not ResourceInfo:
            # Call is already for a subclass, so pass it through
            return super(ResourceInfo, cls).__new__(cls)

        name = path[-1]
        if name.endswith(('.yaml', '.template')):
            # a template url for the resource "Type"
            klass = TemplateResourceInfo
        elif not isinstance(value, six.string_types):
            klass = ClassResourceInfo
        elif value.endswith(('.yaml', '.template')):
            # a registered template
            klass = TemplateResourceInfo
        elif name.endswith('*'):
            klass = GlobResourceInfo
        else:
            klass = MapResourceInfo

        return super(ResourceInfo, cls).__new__(klass)

    __slots__ = ('_registry', 'path', 'name', 'value', 'user_resource')

    def __init__(self, registry, path, value):
        self._registry = weakref.ref(registry)
        self.path = path
        self.name = path[-1]
        self.value = value
        self.user_resource = True

    @property
    def registry(self):
        return self._registry()

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

    def get_class(self):
        raise NotImplementedError

    def get_class_to_instantiate(self):
        return self.get_class()

    def __str__(self):
        return '[%s](User:%s) %s -> %s' % (self.description,
                                           self.user_resource,
                                           self.name, str(self.value))


class ClassResourceInfo(ResourceInfo):
    """Store the mapping of resource name to python class implementation."""
    description = 'Plugin'

    __slots__ = tuple()

    def get_class(self, files=None):
        return self.value


class TemplateResourceInfo(ResourceInfo):
    """Store the info needed to start a TemplateResource."""
    description = 'Template'

    __slots__ = ('template_name',)

    def __init__(self, registry, path, value):
        super(TemplateResourceInfo, self).__init__(registry, path, value)
        if self.name.endswith(('.yaml', '.template')):
            self.template_name = self.name
        else:
            self.template_name = value
        self.value = self.template_name

    def get_class(self, files=None):
        from heat.engine.resources import template_resource
        if files and self.template_name in files:
            data = files[self.template_name]
        else:
            if self.user_resource:
                allowed_schemes = template_resource.REMOTE_SCHEMES
            else:
                allowed_schemes = template_resource.LOCAL_SCHEMES
            data = template_resource.TemplateResource.get_template_file(
                self.template_name,
                allowed_schemes)
        param_defaults = self.registry.param_defaults
        return template_resource.generate_class_from_template(str(self.name),
                                                              data,
                                                              param_defaults)

    def get_class_to_instantiate(self):
        from heat.engine.resources import template_resource
        return template_resource.TemplateResource


class MapResourceInfo(ResourceInfo):
    """Store the mapping of one resource type to another.

    like: OS::Networking::FloatingIp -> OS::Neutron::FloatingIp
    """
    description = 'Mapping'

    __slots__ = tuple()

    def get_class(self, files=None):
        return None

    def get_resource_info(self, resource_type=None, resource_name=None):
        return self.registry.get_resource_info(self.value, resource_name)


class GlobResourceInfo(MapResourceInfo):
    """Store the mapping (with wild cards) of one resource type to another.

    like: OS::Networking::* -> OS::Neutron::*

    Also supports many-to-one mapping (mostly useful together with special
    "OS::Heat::None" resource)

    like: OS::* -> OS::Heat::None
    """
    description = 'Wildcard Mapping'

    __slots__ = tuple()

    def get_resource_info(self, resource_type=None, resource_name=None):
        # NOTE(pas-ha) we end up here only when self.name already
        # ends with * so truncate it
        orig_prefix = self.name[:-1]
        if self.value.endswith('*'):
            new_type = self.value[:-1] + resource_type[len(orig_prefix):]
        else:
            new_type = self.value

        return self.registry.get_resource_info(new_type, resource_name)

    def matches(self, resource_type):
        # prevent self-recursion in case of many-to-one mapping
        match = (resource_type != self.value and
                 resource_type.startswith(self.name[:-1]))
        return match


class ResourceRegistry(object):
    """By looking at the environment, find the resource implementation."""

    def __init__(self, global_registry, param_defaults):
        self._registry = {'resources': {}}
        self.global_registry = global_registry
        self.param_defaults = param_defaults

    def load(self, json_snippet):
        self._load_registry([], json_snippet)

    def register_class(self, resource_type, resource_class, path=None):
        if path is None:
            path = [resource_type]
        ri = ResourceInfo(self, path, resource_class)
        self._register_info(path, ri)

    def _load_registry(self, path, registry):
        for k, v in iter(registry.items()):
            if v is None:
                self._register_info(path + [k], None)
            elif is_hook_definition(k, v) or is_valid_restricted_action(k, v):
                self._register_item(path + [k], v)
            elif isinstance(v, dict):
                self._load_registry(path + [k], v)
            else:
                self._register_info(path + [k],
                                    ResourceInfo(self, path + [k], v))

    def _register_item(self, path, item):
        name = path[-1]
        registry = self._registry
        for key in path[:-1]:
            if key not in registry:
                registry[key] = {}
            registry = registry[key]
        registry[name] = item

    def _register_info(self, path, info):
        """Place the new info in the correct location in the registry.

        :param path: a list of keys ['resources', 'my_srv', 'OS::Nova::Server']
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
                for res_name, reg_info in list(registry.items()):
                    if (isinstance(reg_info, ResourceInfo) and
                            res_name.startswith(name[:-1])):
                        LOG.warning('Removing %(item)s from %(path)s', {
                            'item': res_name,
                            'path': descriptive_path})
                        del registry[res_name]
            else:
                # delete this entry.
                LOG.warning('Removing %(item)s from %(path)s', {
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
            LOG.warning('Changing %(path)s from %(was)s to %(now)s', details)

        if isinstance(info, ClassResourceInfo):
            if info.value.support_status.status != support.SUPPORTED:
                if info.value.support_status.message is not None:
                    details = {
                        'name': info.name,
                        'status': six.text_type(
                            info.value.support_status.status),
                        'message': six.text_type(
                            info.value.support_status.message)
                        }
                    LOG.warning('%(name)s is %(status)s. %(message)s',
                                details)

        info.user_resource = (self.global_registry is not None)
        registry[name] = info

    def log_resource_info(self, show_all=False, prefix=None):
        registry = self._registry
        prefix = '%s ' % prefix if prefix is not None else ''
        for name in registry:
            if name == 'resources':
                continue
            if show_all or isinstance(registry[name], TemplateResourceInfo):
                msg = ('%(p)sRegistered: %(t)s' %
                       {'p': prefix,
                        't': six.text_type(registry[name])})
                LOG.info(msg)

    def remove_item(self, info):
        if not isinstance(info, TemplateResourceInfo):
            return

        registry = self._registry
        for key in info.path[:-1]:
            registry = registry[key]
        if info.path[-1] in registry:
            registry.pop(info.path[-1])

    def get_rsrc_restricted_actions(self, resource_name):
        """Returns a set of restricted actions.

        For a given resource we get the set of restricted actions.

        Actions are set in this format via `resources`::

            {
                "restricted_actions": [update, replace]
            }

        A restricted_actions value is either `update`, `replace` or a list
        of those values. Resources support wildcard matching. The asterisk
        sign matches everything.
        """
        ress = self._registry['resources']
        restricted_actions = set()
        for name_pattern, resource in six.iteritems(ress):
            if fnmatch.fnmatchcase(resource_name, name_pattern):
                if 'restricted_actions' in resource:
                    actions = resource['restricted_actions']
                    if isinstance(actions, six.string_types):
                        restricted_actions.add(actions)
                    elif isinstance(actions, collections.Sequence):
                        restricted_actions |= set(actions)
        return restricted_actions

    def matches_hook(self, resource_name, hook):
        """Return whether a resource have a hook set in the environment.

        For a given resource and a hook type, we check to see if the passed
        group of resources has the right hook associated with the name.

        Hooks are set in this format via `resources`::

            {
                "res_name": {
                    "hooks": [pre-create, pre-update]
                },
                "*_suffix": {
                    "hooks": pre-create
                },
                "prefix_*": {
                    "hooks": pre-update
                }
            }

        A hook value is either `pre-create`, `pre-update` or a list of those
        values. Resources support wildcard matching. The asterisk sign matches
        everything.
        """
        ress = self._registry['resources']
        for name_pattern, resource in six.iteritems(ress):
            if fnmatch.fnmatchcase(resource_name, name_pattern):
                if 'hooks' in resource:
                    hooks = resource['hooks']
                    if isinstance(hooks, six.string_types):
                        if hook == hooks:
                            return True
                    elif isinstance(hooks, collections.Sequence):
                        if hook in hooks:
                            return True
        return False

    def remove_resources_except(self, resource_name):
        ress = self._registry['resources']
        new_resources = {}
        for name, res in six.iteritems(ress):
            if fnmatch.fnmatchcase(resource_name, name):
                new_resources.update(res)
        if resource_name in ress:
            new_resources.update(ress[resource_name])
        self._registry['resources'] = new_resources

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
        globs = six.moves.filter(is_a_glob, iter(self._registry))
        for pattern in globs:
            if self._registry[pattern].matches(resource_type):
                yield self._registry[pattern]

    def get_resource_info(self, resource_type, resource_name=None,
                          registry_type=None, ignore=None):
        """Find possible matches to the resource type and name.

        Chain the results from the global and user registry to find
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
            try:
                match = info.get_resource_info(resource_type,
                                               resource_name)
            except exception.EntityNotFound:
                continue

            if registry_type is None or isinstance(match, registry_type):
                if ignore is not None and match == ignore:
                    continue
                # NOTE(prazumovsky): if resource_type defined in outer env
                # there is a risk to lose it due to h-eng restarting, so
                # store it to local env (exclude ClassResourceInfo because it
                # loads from resources; TemplateResourceInfo handles by
                # template_resource module).
                if (match and not match.user_resource and
                    not isinstance(info, (TemplateResourceInfo,
                                          ClassResourceInfo))):
                    self._register_info([resource_type], info)
                return match

        raise exception.EntityNotFound(entity='Resource Type',
                                       name=resource_type)

    def get_class(self, resource_type, resource_name=None, files=None):
        info = self.get_resource_info(resource_type,
                                      resource_name=resource_name)
        return info.get_class(files=files)

    def get_class_to_instantiate(self, resource_type, resource_name=None):
        if resource_type == "":
            msg = _('Resource "%s" has no type') % resource_name
            raise exception.StackValidationFailed(message=msg)
        elif resource_type is None:
            msg = _('Non-empty resource type is required '
                    'for resource "%s"') % resource_name
            raise exception.StackValidationFailed(message=msg)
        elif not isinstance(resource_type, six.string_types):
            msg = _('Resource "%s" type is not a string') % resource_name
            raise exception.StackValidationFailed(message=msg)

        try:
            info = self.get_resource_info(resource_type,
                                          resource_name=resource_name)
        except exception.EntityNotFound as exc:
            raise exception.StackValidationFailed(message=six.text_type(exc))

        return info.get_class_to_instantiate()

    def as_dict(self):
        """Return user resources in a dict format."""
        def _as_dict(level):
            tmp = {}
            for k, v in iter(level.items()):
                if isinstance(v, dict):
                    tmp[k] = _as_dict(v)
                elif is_hook_definition(
                        k, v) or is_valid_restricted_action(k, v):
                    tmp[k] = v
                elif v.user_resource:
                    tmp[k] = v.value
            return tmp

        return _as_dict(self._registry)

    def get_types(self,
                  cnxt=None,
                  support_status=None,
                  type_name=None,
                  version=None,
                  with_description=False):
        """Return a list of valid resource types."""

        # validate the support status
        if support_status is not None and not support.is_valid_status(
                support_status):
            msg = (_('Invalid support status and should be one of %s') %
                   six.text_type(support.SUPPORT_STATUSES))
            raise exception.Invalid(reason=msg)

        def is_resource(key):
            return isinstance(self._registry[key], (ClassResourceInfo,
                                                    TemplateResourceInfo))

        def status_matches(cls):
            return (support_status is None or
                    cls.get_class().support_status.status ==
                    support_status)

        def is_available(cls):
            if cnxt is None:
                return True

            try:
                return cls.get_class().is_service_available(cnxt)[0]
            except Exception:
                return False

        def not_hidden_matches(cls):
            return cls.get_class().support_status.status != support.HIDDEN

        def is_allowed(enforcer, name):
            if cnxt is None:
                return True
            try:
                enforcer.enforce(cnxt, name, is_registered_policy=True)
            except enforcer.exc:
                return False
            else:
                return True

        enforcer = policy.ResourceEnforcer()

        def name_matches(name):
            try:
                return type_name is None or re.match(type_name, name)
            except:  # noqa
                return False

        def version_matches(cls):
            return (version is None or
                    cls.get_class().support_status.version == version)

        import heat.engine.resource

        def resource_description(name, info, with_description):
            if not with_description:
                return name
            rsrc_cls = info.get_class()
            if rsrc_cls is None:
                rsrc_cls = heat.engine.resource.Resource
            return {
                'resource_type': name,
                'description': rsrc_cls.getdoc(),
            }

        return [resource_description(name, cls, with_description)
                for name, cls in six.iteritems(self._registry)
                if (is_resource(name) and
                    name_matches(name) and
                    status_matches(cls) and
                    is_available(cls) and
                    is_allowed(enforcer, name) and
                    not_hidden_matches(cls) and
                    version_matches(cls))]


class Environment(object):

    def __init__(self, env=None, user_env=True):
        """Create an Environment from an input dict.

        The dict may be in one of two formats:
          1) old-school flat parameters; or
          2) newer {resource_registry: bla, parameters: foo}

        :param env: the json environment
        :param user_env: boolean, if False then we manage python resources too.
        """
        if env is None:
            env = {}
        if user_env:
            from heat.engine import resources
            global_env = resources.global_env()
            global_registry = global_env.registry
            event_sink_classes = global_env.event_sink_classes
        else:
            global_registry = None
            event_sink_classes = {}

        self.param_defaults = env.get(env_fmt.PARAMETER_DEFAULTS, {})

        self.registry = ResourceRegistry(global_registry, self.param_defaults)
        self.registry.load(env.get(env_fmt.RESOURCE_REGISTRY, {}))

        self.encrypted_param_names = env.get(env_fmt.ENCRYPTED_PARAM_NAMES, [])

        if env_fmt.PARAMETERS in env:
            self.params = env[env_fmt.PARAMETERS]
        else:
            self.params = dict((k, v) for (k, v) in six.iteritems(env)
                               if k not in (env_fmt.PARAMETER_DEFAULTS,
                                            env_fmt.ENCRYPTED_PARAM_NAMES,
                                            env_fmt.EVENT_SINKS,
                                            env_fmt.RESOURCE_REGISTRY))
        self.event_sink_classes = event_sink_classes
        self._event_sinks = []
        self._built_event_sinks = []
        self._update_event_sinks(env.get(env_fmt.EVENT_SINKS, []))
        self.constraints = {}
        self.stack_lifecycle_plugins = []

    def load(self, env_snippet):
        self.registry.load(env_snippet.get(env_fmt.RESOURCE_REGISTRY, {}))
        self.params.update(env_snippet.get(env_fmt.PARAMETERS, {}))
        self.param_defaults.update(
            env_snippet.get(env_fmt.PARAMETER_DEFAULTS, {}))
        self._update_event_sinks(env_snippet.get(env_fmt.EVENT_SINKS, []))

    def env_as_dict(self):
        """Get the entire environment as a dict."""
        user_env = self.user_env_as_dict()
        user_env.update(
            # Any data here is to be stored in the DB but not reflected
            # as part of the user environment (e.g to pass to nested stacks
            # or made visible to the user via API calls etc
            {env_fmt.ENCRYPTED_PARAM_NAMES: self.encrypted_param_names})
        return user_env

    def user_env_as_dict(self):
        """Get the environment as a dict, only user-allowed keys."""
        return {env_fmt.RESOURCE_REGISTRY: self.registry.as_dict(),
                env_fmt.PARAMETERS: self.params,
                env_fmt.PARAMETER_DEFAULTS: self.param_defaults,
                env_fmt.EVENT_SINKS: self._event_sinks}

    def register_class(self, resource_type, resource_class, path=None):
        self.registry.register_class(resource_type, resource_class, path=path)

    def register_constraint(self, constraint_name, constraint):
        self.constraints[constraint_name] = constraint

    def register_stack_lifecycle_plugin(self, stack_lifecycle_name,
                                        stack_lifecycle_class):
        self.stack_lifecycle_plugins.append((stack_lifecycle_name,
                                             stack_lifecycle_class))

    def register_event_sink(self, event_sink_name, event_sink_class):
        self.event_sink_classes[event_sink_name] = event_sink_class

    def get_class(self, resource_type, resource_name=None, files=None):
        return self.registry.get_class(resource_type, resource_name,
                                       files=files)

    def get_class_to_instantiate(self, resource_type, resource_name=None):
        return self.registry.get_class_to_instantiate(resource_type,
                                                      resource_name)

    def get_types(self,
                  cnxt=None,
                  support_status=None,
                  type_name=None,
                  version=None,
                  with_description=False):
        return self.registry.get_types(cnxt,
                                       support_status=support_status,
                                       type_name=type_name,
                                       version=version,
                                       with_description=with_description)

    def get_resource_info(self, resource_type, resource_name=None,
                          registry_type=None, ignore=None):
        return self.registry.get_resource_info(resource_type, resource_name,
                                               registry_type, ignore=ignore)

    def get_constraint(self, name):
        return self.constraints.get(name)

    def get_stack_lifecycle_plugins(self):
        return self.stack_lifecycle_plugins

    def _update_event_sinks(self, sinks):
        self._event_sinks.extend(sinks)
        for sink in sinks:
            sink = sink.copy()
            sink_class = sink.pop('type')
            sink_class = self.event_sink_classes[sink_class]
            self._built_event_sinks.append(sink_class(**sink))

    def get_event_sinks(self):
        return self._built_event_sinks


def get_child_environment(parent_env, child_params, item_to_remove=None,
                          child_resource_name=None):
    """Build a child environment using the parent environment and params.

    This is built from the child_params and the parent env so some
    resources can use user-provided parameters as if they come from an
    environment.

    1. resource_registry must be merged (child env should be loaded after the
       parent env to take precedence).
    2. child parameters must overwrite the parent's as they won't be relevant
       in the child template.

    If `child_resource_name` is provided, resources in the registry will be
    replaced with the contents of the matching child resource plus anything
    that passes a wildcard match.
    """
    def is_flat_params(env_or_param):
        if env_or_param is None:
            return False
        for sect in env_fmt.SECTIONS:
            if sect in env_or_param:
                return False
        return True

    child_env = parent_env.user_env_as_dict()
    child_env[env_fmt.PARAMETERS] = {}
    flat_params = is_flat_params(child_params)
    new_env = Environment()
    if flat_params and child_params is not None:
        child_env[env_fmt.PARAMETERS] = child_params

    new_env.load(child_env)
    if not flat_params and child_params is not None:
        new_env.load(child_params)

    if item_to_remove is not None:
        new_env.registry.remove_item(item_to_remove)

    if child_resource_name:
        new_env.registry.remove_resources_except(child_resource_name)
    return new_env


def read_global_environment(env, env_dir=None):
    if env_dir is None:
        cfg.CONF.import_opt('environment_dir', 'heat.common.config')
        env_dir = cfg.CONF.environment_dir

    try:
        env_files = glob.glob(os.path.join(env_dir, '*'))
    except OSError:
        LOG.exception('Failed to read %s', env_dir)
        return

    for file_path in env_files:
        try:
            with open(file_path) as env_fd:
                LOG.info('Loading %s', file_path)
                env_body = env_fmt.parse(env_fd.read())
                env_fmt.default_for_missing(env_body)
                env.load(env_body)
        except ValueError:
            LOG.exception('Failed to parse %s', file_path)
        except IOError:
            LOG.exception('Failed to read %s', file_path)
