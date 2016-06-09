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

import base64
import contextlib
import datetime as dt
import warnings
import weakref

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import reflection
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LE
from heat.common.i18n import _LI
from heat.common.i18n import _LW
from heat.common import identifier
from heat.common import short_id
from heat.common import timeutils
from heat.engine import attributes
from heat.engine.cfn import template as cfn_tmpl
from heat.engine import clients
from heat.engine import environment
from heat.engine import event
from heat.engine import function
from heat.engine.hot import template as hot_tmpl
from heat.engine import properties
from heat.engine import resources
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import support
from heat.objects import resource as resource_objects
from heat.objects import resource_data as resource_data_objects
from heat.objects import stack as stack_objects
from heat.rpc import client as rpc_client

cfg.CONF.import_opt('action_retry_limit', 'heat.common.config')
cfg.CONF.import_opt('observe_on_update', 'heat.common.config')

LOG = logging.getLogger(__name__)

datetime = dt.datetime


def _register_class(resource_type, resource_class):
    resources.global_env().register_class(resource_type, resource_class)


class PollDelay(Exception):
    """Exception to delay polling of the resource.

    This exception may be raised by a Resource subclass's check_*_complete()
    methods to indicate that it need not be polled again immediately. If this
    exception is raised, the check_*_complete() method will not be called
    again until the nth time that the resource becomes eligible for polling.
    A PollDelay period of 1 is equivalent to returning False.
    """
    def __init__(self, period):
        assert period >= 1
        self.period = period


@six.python_2_unicode_compatible
class Resource(object):
    ACTIONS = (
        INIT, CREATE, DELETE, UPDATE, ROLLBACK,
        SUSPEND, RESUME, ADOPT, SNAPSHOT, CHECK,
    ) = (
        'INIT', 'CREATE', 'DELETE', 'UPDATE', 'ROLLBACK',
        'SUSPEND', 'RESUME', 'ADOPT', 'SNAPSHOT', 'CHECK',
    )

    STATUSES = (IN_PROGRESS, FAILED, COMPLETE
                ) = ('IN_PROGRESS', 'FAILED', 'COMPLETE')

    BASE_ATTRIBUTES = (SHOW, ) = ('show', )

    # If True, this resource must be created before it can be referenced.
    strict_dependency = True

    # Resource implementation set this to the subset of resource properties
    # supported for handle_update, used by update_template_diff_properties
    update_allowed_properties = ()

    # Resource implementations set this to the name: description dictionary
    # that describes the appropriate resource attributes
    attributes_schema = {}

    # Resource implementations set this to update policies
    update_policy_schema = {}

    # Default entity of resource, which is used for during resolving
    # show attribute
    entity = None

    # Description dictionary, that describes the common attributes for all
    # resources
    base_attributes_schema = {
        SHOW: attributes.Schema(
            _("Detailed information about resource."),
            type=attributes.Schema.MAP
        )
    }

    # If True, this resource may perform authenticated API requests
    # throughout its lifecycle
    requires_deferred_auth = False

    # Limit to apply to physical_resource_name() size reduction algorithm.
    # If set to None no limit will be applied.
    physical_resource_name_limit = 255

    support_status = support.SupportStatus()

    # Default name to use for calls to self.client()
    default_client_name = None

    # Required service extension for this resource
    required_service_extension = None

    # no signal actions
    no_signal_actions = (SUSPEND, DELETE)

    # Whether all other resources need a metadata_update() after
    # a signal to this resource
    signal_needs_metadata_updates = True

    def __new__(cls, name, definition, stack):
        """Create a new Resource of the appropriate class for its type."""

        assert isinstance(definition, rsrc_defn.ResourceDefinition)

        if cls != Resource:
            # Call is already for a subclass, so pass it through
            ResourceClass = cls
        else:
            registry = stack.env.registry
            ResourceClass = registry.get_class_to_instantiate(
                definition.resource_type,
                resource_name=name)

            assert issubclass(ResourceClass, Resource)

        if not stack.service_check_defer:
            ResourceClass._validate_service_availability(
                stack.context,
                definition.resource_type
            )

        return super(Resource, cls).__new__(ResourceClass)

    @classmethod
    def _validate_service_availability(cls, context, resource_type):
        try:
            svc_available = cls.is_service_available(context)
        except Exception as exc:
            ex = exception.ResourceTypeUnavailable(
                resource_type=resource_type,
                service_name=cls.default_client_name,
                reason=six.text_type(exc))
            LOG.exception(exc)
            raise ex
        else:
            if not svc_available:
                ex = exception.ResourceTypeUnavailable(
                    resource_type=resource_type,
                    service_name=cls.default_client_name,
                    reason='Service endpoint not in service catalog.')
                LOG.info(six.text_type(ex))
                raise ex

    def _init_attributes(self):
        """The method that defines attribute initialization for a resource.

        Some resource requires different initialization of resource attributes.
        So they must override this method and return the initialized
        attributes to the resource.
        :return: resource attributes
        """
        return attributes.Attributes(self.name,
                                     self.attributes_schema,
                                     self._resolve_all_attributes)

    def __init__(self, name, definition, stack):

        def _validate_name(res_name):
            if '/' in res_name:
                message = _('Resource name may not contain "/"')
                raise exception.StackValidationFailed(message=message)

        _validate_name(name)
        self.stack = stack
        self.context = stack.context
        self.name = name
        self.t = definition
        # Only translate in cases where resource_validate is True
        # ex. for template-validate
        self.reparse(translate=self.stack.resource_validate,
                     client_resolve=False)
        self.update_policy = self.t.update_policy(self.update_policy_schema,
                                                  self.context)
        self.attributes_schema.update(self.base_attributes_schema)
        self.attributes = self._init_attributes()

        self.abandon_in_progress = False

        self.resource_id = None
        # if the stack is being deleted, assume we've already been deleted.
        # or if the resource has not been created yet, and the stack was
        # rollback, we set the resource to rollback
        if stack.action == stack.DELETE or stack.action == stack.ROLLBACK:
            self.action = stack.action
        else:
            self.action = self.INIT
        self.status = self.COMPLETE
        self.status_reason = ''
        self.id = None
        self.uuid = None
        self._data = None
        self._rsrc_metadata = None
        self._stored_properties_data = None
        self.created_time = stack.created_time
        self.updated_time = stack.updated_time
        self._rpc_client = None
        self.needed_by = []
        self.requires = []
        self.replaces = None
        self.replaced_by = None
        self.current_template_id = None
        self.root_stack_id = None

        if not stack.has_cache_data(name):
            resource = stack.db_resource_get(name)
            if resource:
                self._load_data(resource)
        else:
            self.action = stack.cache_data[name]['action']
            self.status = stack.cache_data[name]['status']
            self.id = stack.cache_data[name]['id']
            self.uuid = stack.cache_data[name]['uuid']

    def rpc_client(self):
        """Return a client for making engine RPC calls."""
        if not self._rpc_client:
            self._rpc_client = rpc_client.EngineClient()
        return self._rpc_client

    def _load_data(self, resource):
        """Load the resource state from its DB representation."""
        self.resource_id = resource.physical_resource_id
        self.action = resource.action
        self.status = resource.status
        self.status_reason = resource.status_reason
        self.id = resource.id
        self.uuid = resource.uuid
        try:
            self._data = resource_data_objects.ResourceData.get_all(
                self, resource.data)
        except exception.NotFound:
            self._data = {}
        self._rsrc_metadata = resource.rsrc_metadata
        self._stored_properties_data = resource.properties_data
        self.created_time = resource.created_at
        self.updated_time = resource.updated_at
        self.needed_by = resource.needed_by
        self.requires = resource.requires
        self.replaces = resource.replaces
        self.replaced_by = resource.replaced_by
        self.current_template_id = resource.current_template_id
        self.root_stack_id = resource.root_stack_id

    @property
    def stack(self):
        stack = self._stackref()
        assert stack is not None, "Need a reference to the Stack object"
        return stack

    @stack.setter
    def stack(self, stack):
        self._stackref = weakref.ref(stack)

    @classmethod
    def load(cls, context, resource_id, is_update, data):
        from heat.engine import stack as stack_mod
        db_res = resource_objects.Resource.get_obj(context, resource_id)
        curr_stack = stack_mod.Stack.load(context, stack_id=db_res.stack_id,
                                          cache_data=data)

        resource_owning_stack = curr_stack
        if db_res.current_template_id != curr_stack.t.id:
            # load stack with template owning the resource
            db_stack = stack_objects.Stack.get_by_id(context, db_res.stack_id)
            db_stack.raw_template = None
            db_stack.raw_template_id = db_res.current_template_id
            resource_owning_stack = stack_mod.Stack.load(context,
                                                         stack=db_stack)

        # Load only the resource in question; don't load all resources
        # by invoking stack.resources. Maintain light-weight stack.
        res_defn = resource_owning_stack.t.resource_definitions(
            resource_owning_stack)[db_res.name]
        resource = cls(db_res.name, res_defn, resource_owning_stack)
        resource._load_data(db_res)

        # assign current stack to the resource for updates
        if is_update:
            resource.stack = curr_stack

        # return resource owning stack so that it is not GCed since it
        # is the only stack instance with a weak-ref from resource
        return resource, resource_owning_stack, curr_stack

    def make_replacement(self, new_tmpl_id):
        # 1. create the replacement with "replaces" = self.id
        #  Don't set physical_resource_id so that a create is triggered.
        rs = {'stack_id': self.stack.id,
              'name': self.name,
              'properties_data': self._stored_properties_data,
              'needed_by': self.needed_by,
              'requires': self.requires,
              'replaces': self.id,
              'action': self.INIT,
              'status': self.COMPLETE,
              'current_template_id': new_tmpl_id,
              'stack_name': self.stack.name,
              'root_stack_id': self.root_stack_id}
        new_rs = resource_objects.Resource.create(self.context, rs)

        # 2. update the current resource to be replaced_by the one above.
        self.replaced_by = new_rs.id
        resource_objects.Resource.update_by_id(
            self.context, self.id,
            {'status': self.COMPLETE, 'replaced_by': self.replaced_by})
        return new_rs.id

    def reparse(self, translate=True, client_resolve=True):
        """Reparse the resource properties.

        Optional translate flag for property translation and
        client_resolve flag for resolving properties by doing
        client lookup.
        """
        self.properties = self.t.properties(self.properties_schema,
                                            self.context)
        if translate:
            self.translate_properties(self.properties, client_resolve)

    def __eq__(self, other):
        """Allow == comparison of two resources."""
        # For the purposes of comparison, we declare two resource objects
        # equal if their names and resolved templates are the same
        if isinstance(other, Resource):
            return ((self.name == other.name) and
                    (self.t.freeze() == other.t.freeze()))
        return NotImplemented

    def __ne__(self, other):
        """Allow != comparison of two resources."""
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __hash__(self):
        return id(self)

    def metadata_get(self, refresh=False):
        if refresh:
            self._rsrc_metadata = None
        if self.id is None or self.action == self.INIT:
            return self.t.metadata()
        if self._rsrc_metadata is not None:
            return self._rsrc_metadata
        rs = resource_objects.Resource.get_obj(self.stack.context, self.id)
        rs.refresh(attrs=['rsrc_metadata'])
        self._rsrc_metadata = rs.rsrc_metadata
        return rs.rsrc_metadata

    @resource_objects.retry_on_conflict
    def metadata_set(self, metadata, merge_metadata=None):
        """Write new metadata to the database.

        The caller may optionally provide a merge_metadata() function, which
        takes two arguments - the metadata passed to metadata_set() and the
        current metadata of the resource - and returns the merged metadata to
        write. If merge_metadata is not provided, the metadata passed to
        metadata_set() is written verbatim, overwriting any existing metadata.

        If a race condition is detected, the write will be retried with the new
        result of merge_metadata() (if it is supplied) or the verbatim data (if
        it is not).
        """
        if self.id is None or self.action == self.INIT:
            raise exception.ResourceNotAvailable(resource_name=self.name)
        LOG.debug('Setting metadata for %s', six.text_type(self))
        db_res = resource_objects.Resource.get_obj(self.stack.context, self.id)
        if merge_metadata is not None:
            db_res = db_res.refresh(attrs=['rsrc_metadata'])
            metadata = merge_metadata(metadata, db_res.rsrc_metadata)
        db_res.update_metadata(metadata)
        self._rsrc_metadata = metadata

    @classmethod
    def set_needed_by(cls, db_rsrc, needed_by, expected_engine_id=None):
        if db_rsrc:
            db_rsrc.select_and_update(
                {'needed_by': needed_by},
                atomic_key=db_rsrc.atomic_key,
                expected_engine_id=expected_engine_id
            )

    @classmethod
    def set_requires(cls, db_rsrc, requires):
        if db_rsrc:
            db_rsrc.update_and_save(
                {'requires': requires}
            )

    def _break_if_required(self, action, hook):
        """Block the resource until the hook is cleared if there is one."""
        if self.stack.env.registry.matches_hook(self.name, hook):
            self._add_event(self.action, self.status,
                            _("%(a)s paused until Hook %(h)s is cleared")
                            % {'a': action, 'h': hook})
            self.trigger_hook(hook)
            LOG.info(_LI('Reached hook on %s'), six.text_type(self))

            while self.has_hook(hook) and self.status != self.FAILED:
                try:
                    yield
                except BaseException as exc:
                    self.clear_hook(hook)
                    self._add_event(
                        self.action, self.status,
                        "Failure occurred while waiting.")
                    if (isinstance(exc, AssertionError) or
                            not isinstance(exc, Exception)):
                        raise

    def has_nested(self):
        # common resources have not nested, StackResource overrides it
        return False

    def has_hook(self, hook):
        # Clear the cache to make sure the data is up to date:
        self._data = None
        return self.data().get(hook) == "True"

    def trigger_hook(self, hook):
        self.data_set(hook, "True")

    def clear_hook(self, hook):
        self.data_delete(hook)

    def type(self):
        return self.t.resource_type

    def has_interface(self, resource_type):
        """Check if resource is mapped to resource_type or is "resource_type".

        Check to see if this resource is either mapped to resource_type
        or is a "resource_type".
        """
        if self.type() == resource_type:
            return True

        try:
            ri = self.stack.env.get_resource_info(self.type(),
                                                  self.name)
        except exception.EntityNotFound:
            return False
        else:
            return ri.name == resource_type

    def identifier(self):
        """Return an identifier for this resource."""
        return identifier.ResourceIdentifier(resource_name=self.name,
                                             **self.stack.identifier())

    def parsed_template(self, section=None, default=None):
        """Return the parsed template data for the resource.

        May be limited to only one section of the data, in which case a default
        value may also be supplied.
        """
        warnings.warn('Resource.parsed_template() is deprecated and will be '
                      'removed in the Ocata release. Use the '
                      'ResourceDefinition API instead.',
                      DeprecationWarning)

        frozen = self.t.freeze()
        if section is None:
            return frozen

        return frozen.get(section, default or {})

    def frozen_definition(self):
        if self._stored_properties_data is not None:
            args = {'properties': self._stored_properties_data}
        else:
            args = {}
        return self.t.freeze(**args)

    def update_template_diff(self, after, before):
        """Returns the difference between the before and after json snippets.

        If something has been removed in after which exists in before we set it
        to None.
        """
        return after - before

    def update_template_diff_properties(self, after_props, before_props):
        """Return changed Properties between the before and after properties.

        If any property having immutable as True is updated, raises
        NotSupported error.
        If any properties have changed which are not in
        update_allowed_properties, raises UpdateReplace.
        """
        update_allowed_set = set(self.update_allowed_properties)
        immutable_set = set()
        for (psk, psv) in six.iteritems(self.properties.props):
            if psv.update_allowed():
                update_allowed_set.add(psk)
            if psv.immutable():
                immutable_set.add(psk)

        def prop_changed(key):
            try:
                before = before_props.get(key)
            except (TypeError, ValueError) as exc:
                # We shouldn't get here usually, but there is a known issue
                # with template resources and new parameters in non-convergence
                # stacks (see bug 1543685). The error should be harmless
                # because we're on the before properties, which have presumably
                # already been validated.
                LOG.warning(_LW('Ignoring error in old property value '
                                '%(prop_name)s: %(msg)s'),
                            {'prop_name': key, 'msg': six.text_type(exc)})
                return True

            return before != after_props.get(key)

        # Create a set of keys which differ (or are missing/added)
        changed_properties_set = set(k for k in after_props if prop_changed(k))

        # Create a list of updated properties offending property immutability
        update_replace_forbidden = [k for k in changed_properties_set
                                    if k in immutable_set]

        if update_replace_forbidden:
            mesg = _("Update to properties %(props)s of %(name)s (%(res)s)"
                     ) % {'props': ", ".join(sorted(update_replace_forbidden)),
                          'res': self.type(), 'name': self.name}
            raise exception.NotSupported(feature=mesg)

        if changed_properties_set and self.needs_replace_with_prop_diff(
                changed_properties_set,
                after_props,
                before_props):
            raise exception.UpdateReplace(self)

        if not changed_properties_set.issubset(update_allowed_set):
            raise exception.UpdateReplace(self.name)

        return dict((k, after_props.get(k)) for k in changed_properties_set)

    def __str__(self):
        class_name = reflection.get_class_name(self, fully_qualified=False)
        if self.stack.id:
            if self.resource_id:
                text = '%s "%s" [%s] %s' % (class_name, self.name,
                                            self.resource_id,
                                            six.text_type(self.stack))
            else:
                text = '%s "%s" %s' % (class_name, self.name,
                                       six.text_type(self.stack))
        else:
            text = '%s "%s"' % (class_name, self.name)
        return six.text_type(text)

    def dep_attrs(self, resource_name):
        return self.t.dep_attrs(resource_name)

    def add_explicit_dependencies(self, deps):
        """Add all dependencies explicitly specified in the template.

        The deps parameter is a Dependencies object to which dependency pairs
        are added.
        """
        for dep in self.t.dependencies(self.stack):
            deps += (self, dep)
        deps += (self, None)

    def add_dependencies(self, deps):
        """Add implicit dependencies specific to the resource type.

        Some resource types may have implicit dependencies on other resources
        in the same stack that are not linked by a property value (that would
        be set using get_resource or get_attr for example, thus creating an
        explicit dependency). Such dependencies are opaque to the user and
        should be avoided wherever possible, however in some circumstances they
        are required due to magic in the underlying API.

        The deps parameter is a Dependencies object to which dependency pairs
        may be added.
        """
        return

    def required_by(self):
        """List of resources that require this one as a dependency.

        Returns a list of names of resources that depend on this resource
        directly.
        """
        return [r.name for r in self.stack.dependencies.required_by(self)]

    def client(self, name=None, version=None):
        client_name = name or self.default_client_name
        assert client_name, "Must specify client name"
        return self.stack.clients.client(client_name, version)

    def client_plugin(self, name=None):
        client_name = name or self.default_client_name
        assert client_name, "Must specify client name"
        return self.stack.clients.client_plugin(client_name)

    @classmethod
    def is_service_available(cls, context):
        # NOTE(kanagaraj-manickam): return True to satisfy the cases like
        # resource does not have endpoint, such as RandomString, OS::Heat
        # resources as they are implemented within the engine.
        if cls.default_client_name is None:
            return True
        client_plugin = clients.Clients(context).client_plugin(
            cls.default_client_name)

        if not client_plugin:
            raise exception.ClientNotAvailable(
                client_name=cls.default_client_name)

        service_types = client_plugin.service_types
        if not service_types:
            return True

        # NOTE(kanagaraj-manickam): if one of the service_type does
        # exist in the keystone, then considered it as available.
        for service_type in service_types:
            endpoint_exists = client_plugin.does_endpoint_exist(
                service_type=service_type,
                service_name=cls.default_client_name)
            if endpoint_exists:
                req_extension = cls.required_service_extension
                is_ext_available = (
                    not req_extension or client_plugin.has_extension(
                        req_extension))
                if is_ext_available:
                    return True
        return False

    def keystone(self):
        return self.client('keystone')

    def nova(self):
        return self.client('nova')

    def swift(self):
        return self.client('swift')

    def neutron(self):
        return self.client('neutron')

    def cinder(self):
        return self.client('cinder')

    def trove(self):
        return self.client('trove')

    def ceilometer(self):
        return self.client('ceilometer')

    def heat(self):
        return self.client('heat')

    def glance(self):
        return self.client('glance')

    @contextlib.contextmanager
    def _action_recorder(self, action, expected_exceptions=tuple()):
        """Return a context manager to record the progress of an action.

        Upon entering the context manager, the state is set to IN_PROGRESS.
        Upon exiting, the state will be set to COMPLETE if no exception was
        raised, or FAILED otherwise. Non-exit exceptions will be translated
        to ResourceFailure exceptions.

        Expected exceptions are re-raised, with the Resource moved to the
        COMPLETE state.
        """
        try:
            self.state_set(action, self.IN_PROGRESS)
            yield
        except expected_exceptions as ex:
            with excutils.save_and_reraise_exception():
                self.state_set(action, self.COMPLETE, six.text_type(ex))
                LOG.debug('%s', six.text_type(ex))
        except Exception as ex:
            LOG.info(_LI('%(action)s: %(info)s'),
                     {"action": action,
                      "info": six.text_type(self)},
                     exc_info=True)
            failure = exception.ResourceFailure(ex, self, action)
            self.state_set(action, self.FAILED, six.text_type(failure))
            raise failure
        except:  # noqa
            with excutils.save_and_reraise_exception():
                try:
                    self.state_set(action, self.FAILED, '%s aborted' % action)
                except Exception:
                    LOG.exception(_LE('Error marking resource as failed'))
        else:
            self.state_set(action, self.COMPLETE)

    def action_handler_task(self, action, args=None, action_prefix=None):
        """A task to call the Resource subclass's handler methods for action.

        Calls the handle_<ACTION>() method for the given action and then calls
        the check_<ACTION>_complete() method with the result in a loop until it
        returns True. If the methods are not provided, the call is omitted.

        Any args provided are passed to the handler.

        If a prefix is supplied, the handler method handle_<PREFIX>_<ACTION>()
        is called instead.
        """
        args = args or []
        handler_action = action.lower()
        check = getattr(self, 'check_%s_complete' % handler_action, None)

        if action_prefix:
            handler_action = '%s_%s' % (action_prefix.lower(), handler_action)
        handler = getattr(self, 'handle_%s' % handler_action, None)

        if callable(handler):
            handler_data = handler(*args)
            yield
            if callable(check):
                while True:
                    try:
                        done = check(handler_data)
                    except PollDelay as delay:
                        yield delay.period
                    else:
                        if done:
                            break
                        else:
                            yield

    @scheduler.wrappertask
    def _do_action(self, action, pre_func=None, resource_data=None):
        """Perform a transition to a new state via a specified action.

        Action should be e.g self.CREATE, self.UPDATE etc, we set
        status based on this, the transition is handled by calling the
        corresponding handle_* and check_*_complete functions
        Note pre_func is an optional function reference which will
        be called before the handle_<action> function

        If the resource does not declare a check_$action_complete function,
        we declare COMPLETE status as soon as the handle_$action call has
        finished, and if no handle_$action function is declared, then we do
        nothing, useful e.g if the resource requires no action for a given
        state transition
        """
        assert action in self.ACTIONS, 'Invalid action %s' % action

        with self._action_recorder(action):
            if callable(pre_func):
                pre_func()

            handler_args = [resource_data] if resource_data is not None else []
            yield self.action_handler_task(action, args=handler_args)

    def _update_stored_properties(self):
        self._stored_properties_data = function.resolve(self.properties.data)

    def preview(self):
        """Default implementation of Resource.preview.

        This method should be overridden by child classes for specific
        behavior.
        """
        return self

    def create_convergence(self, template_id, resource_data, engine_id,
                           timeout):
        """Creates the resource by invoking the scheduler TaskRunner."""
        with self.lock(engine_id):
            self.requires = list(
                set(data[u'id'] for data in resource_data.values()
                    if data)
            )
            self.current_template_id = template_id
            if self.stack.adopt_stack_data is None:
                runner = scheduler.TaskRunner(self.create)
            else:
                adopt_data = self.stack._adopt_kwargs(self)
                runner = scheduler.TaskRunner(self.adopt, **adopt_data)
            runner(timeout=timeout)

    @scheduler.wrappertask
    def create(self):
        """Create the resource.

        Subclasses should provide a handle_create() method to customise
        creation.
        """
        action = self.CREATE
        if (self.action, self.status) != (self.INIT, self.COMPLETE):
            exc = exception.Error(_('State %s invalid for create')
                                  % six.text_type(self.state))
            raise exception.ResourceFailure(exc, self, action)

        # This method can be called when we replace a resource, too. In that
        # case, a hook has already been dealt with in `Resource.update` so we
        # shouldn't do it here again:
        if self.stack.action == self.stack.CREATE:
            yield self._break_if_required(
                self.CREATE, environment.HOOK_PRE_CREATE)

        LOG.info(_LI('creating %s'), six.text_type(self))

        # Re-resolve the template, since if the resource Ref's
        # the StackId pseudo parameter, it will change after
        # the parser.Stack is stored (which is after the resources
        # are __init__'d, but before they are create()'d). We also
        # do client lookups for RESOLVE translation rules here.

        self.reparse()
        self._update_stored_properties()

        def pause():
            try:
                while True:
                    yield
            except scheduler.Timeout:
                return

        count = {self.CREATE: 0, self.DELETE: 0}

        retry_limit = max(cfg.CONF.action_retry_limit, 0)
        first_failure = None

        while (count[self.CREATE] <= retry_limit and
               count[self.DELETE] <= retry_limit):
            if count[action]:
                delay = timeutils.retry_backoff_delay(count[action],
                                                      jitter_max=2.0)
                waiter = scheduler.TaskRunner(pause)
                waiter.start(timeout=delay)
                while not waiter.step():
                    yield
            try:
                yield self._do_action(action, self.properties.validate)
                if action == self.CREATE:
                    first_failure = None
                    break
                else:
                    action = self.CREATE
            except exception.ResourceFailure as failure:
                if not isinstance(failure.exc, exception.ResourceInError):
                    raise failure

                count[action] += 1
                if action == self.CREATE:
                    action = self.DELETE
                    count[action] = 0

                if first_failure is None:
                    # Save the first exception
                    first_failure = failure

        if first_failure:
            raise first_failure

        if self.stack.action == self.stack.CREATE:
            yield self._break_if_required(
                self.CREATE, environment.HOOK_POST_CREATE)

    def prepare_abandon(self):
        self.abandon_in_progress = True
        return {
            'name': self.name,
            'resource_id': self.resource_id,
            'type': self.type(),
            'action': self.action,
            'status': self.status,
            'metadata': self.metadata_get(refresh=True),
            'resource_data': self.data()
        }

    def adopt(self, resource_data):
        """Adopt the existing resource.

        Resource subclasses can provide a handle_adopt() method to customise
        adopt.
        """
        self._update_stored_properties()
        return self._do_action(self.ADOPT, resource_data=resource_data)

    def handle_adopt(self, resource_data=None):
        resource_id, data, metadata = self._get_resource_info(resource_data)

        if not resource_id:
            exc = Exception(_('Resource ID was not provided.'))
            failure = exception.ResourceFailure(exc, self)
            raise failure

        # set resource id
        self.resource_id_set(resource_id)

        # save the resource data
        if data and isinstance(data, dict):
            for key, value in six.iteritems(data):
                self.data_set(key, value)

        # save the resource metadata
        self.metadata_set(metadata)

    def translation_rules(self, properties):
        """Return specified rules for resource."""

    def translate_properties(self, properties,
                             client_resolve=True):
        """Translates properties with resource specific rules.

        The properties parameter is a properties object and the
        optional client_resolve flag is to specify whether to
        do 'RESOLVE' translation with client lookup.
        """
        rules = self.translation_rules(properties) or []
        for rule in rules:
            rule.execute_rule(client_resolve)

    def _get_resource_info(self, resource_data):
        if not resource_data:
            return None, None, None

        return (resource_data.get('resource_id'),
                resource_data.get('resource_data'),
                resource_data.get('metadata'))

    def needs_replace(self, after_props):
        """Mandatory replace based on certain properties."""
        return False

    def needs_replace_with_prop_diff(self, changed_properties_set,
                                     after_props, before_props):
        """Needs replace based on prop_diff."""
        return False

    def needs_replace_with_tmpl_diff(self, tmpl_diff):
        """Needs replace based on tmpl_diff."""
        return False

    def _needs_update(self, after, before, after_props, before_props,
                      prev_resource, check_init_complete=True):
        if self.status == self.FAILED:
            raise exception.UpdateReplace(self)

        if check_init_complete and (self.action == self.INIT
                                    and self.status == self.COMPLETE):
            raise exception.UpdateReplace(self)

        if self.needs_replace(after_props):
            raise exception.UpdateReplace(self)

        if before != after.freeze():
            return True

        try:
            return before_props != after_props
        except ValueError:
            return True

    def _check_for_convergence_replace(self, restricted_actions):
        if 'replace' in restricted_actions:
            ex = exception.ResourceActionRestricted(action='replace')
            failure = exception.ResourceFailure(ex, self, self.UPDATE)
            self._add_event(self.UPDATE, self.FAILED, six.text_type(ex))
            raise failure
        else:
            raise exception.UpdateReplace(self.name)

    def update_convergence(self, template_id, resource_data, engine_id,
                           timeout, new_stack):
        """Update the resource synchronously.

        Persist the resource's current_template_id to template_id and
        resource's requires to list of the required resource ids from the given
        resource_data and existing resource's requires, then updates the
        resource by invoking the scheduler TaskRunner.
        """
        def update_tmpl_id_and_requires():
            self.current_template_id = template_id
            self.requires = list(
                set(data[u'id'] for data in resource_data.values()
                    if data is not None)
            )

        with self.lock(engine_id):
            registry = new_stack.env.registry
            new_res_def = new_stack.t.resource_definitions(
                new_stack)[self.name]
            new_res_type = registry.get_class_to_instantiate(
                new_res_def.resource_type, resource_name=self.name)
            restricted_actions = registry.get_rsrc_restricted_actions(
                self.name)

            if type(self) is not new_res_type:
                self._check_for_convergence_replace(restricted_actions)

            action_rollback = self.stack.action == self.stack.ROLLBACK
            status_in_progress = self.stack.status == self.stack.IN_PROGRESS
            if action_rollback and status_in_progress and self.replaced_by:
                try:
                    self.restore_prev_rsrc(convergence=True)
                except Exception as e:
                    failure = exception.ResourceFailure(e, self, self.action)
                    self.state_set(self.UPDATE, self.FAILED,
                                   six.text_type(failure))
                    raise failure

            runner = scheduler.TaskRunner(self.update, new_res_def)
            try:
                runner(timeout=timeout)
                update_tmpl_id_and_requires()
            except exception.ResourceFailure:
                update_tmpl_id_and_requires()
                raise

    def preview_update(self, after, before, after_props, before_props,
                       prev_resource, check_init_complete=False):
        """Simulates update without actually updating the resource.

        Raises UpdateReplace, if replacement is required or returns True,
        if in-place update is required.
        """
        if self._needs_update(after, before, after_props, before_props,
                              prev_resource, check_init_complete):
            tmpl_diff = self.update_template_diff(after.freeze(), before)
            if tmpl_diff and self.needs_replace_with_tmpl_diff(tmpl_diff):
                raise exception.UpdateReplace(self)

            self.update_template_diff_properties(after_props, before_props)
            return True

    def _check_restricted_actions(self, actions, after, before,
                                  after_props, before_props,
                                  prev_resource):
        """Checks for restricted actions.

        Raises ResourceActionRestricted, if the resource requires update
        or replace and the required action is restricted.

        Else, Raises UpdateReplace, if replacement is required or returns
        True, if in-place update is required.
        """
        try:
            if self.preview_update(after, before, after_props, before_props,
                                   prev_resource, check_init_complete=True):
                if 'update' in actions:
                    raise exception.ResourceActionRestricted(action='update')
                return True
        except exception.UpdateReplace:
            if 'replace' in actions:
                raise exception.ResourceActionRestricted(action='replace')
            raise

    def _prepare_update_props(self, after, before):

        before_props = before.properties(self.properties_schema,
                                         self.context)

        # Regenerate the schema, else validation would fail
        self.regenerate_info_schema(after)
        after_props = after.properties(self.properties_schema,
                                       self.context)
        self.translate_properties(after_props)
        self.translate_properties(before_props)

        if cfg.CONF.observe_on_update and before_props:
            if not self.resource_id:
                raise exception.UpdateReplace(self)

            try:
                resource_reality = self.get_live_state(before_props)
                if resource_reality:
                    self._update_properties_with_live_state(before_props,
                                                            resource_reality)
            except exception.EntityNotFound:
                raise exception.UpdateReplace(self)
            except Exception as ex:
                LOG.warning(_LW("Resource cannot be updated with it's "
                                "live state in case of next "
                                "error: %s"), six.text_type(ex))
        return after_props, before_props

    def _prepare_update_replace(self, action):
        try:
            if (self.stack.action == 'ROLLBACK' and
                    self.stack.status == 'IN_PROGRESS' and
                    not cfg.CONF.convergence_engine):
                # handle case, when it's rollback and we should restore
                # old resource
                self.restore_prev_rsrc()
            else:
                self.prepare_for_replace()
        except Exception as e:
            # if any exception happen, we should set the resource to
            # FAILED, then raise ResourceFailure
            failure = exception.ResourceFailure(e, self, action)
            self.state_set(action, self.FAILED, six.text_type(failure))
            raise failure

    @scheduler.wrappertask
    def update(self, after, before=None, prev_resource=None):
        """Return a task to update the resource.

        Subclasses should provide a handle_update() method to customise update,
        the base-class handle_update will fail by default.
        """
        action = self.UPDATE

        assert isinstance(after, rsrc_defn.ResourceDefinition)
        if before is None:
            before = self.frozen_definition()

        after_props, before_props = self._prepare_update_props(
            after, before)

        yield self._break_if_required(
            self.UPDATE, environment.HOOK_PRE_UPDATE)

        try:
            registry = self.stack.env.registry
            restr_actions = registry.get_rsrc_restricted_actions(self.name)
            if restr_actions:
                if not self._check_restricted_actions(restr_actions,
                                                      after, before,
                                                      after_props,
                                                      before_props,
                                                      prev_resource):
                    return
            else:
                if not self._needs_update(after, before,
                                          after_props, before_props,
                                          prev_resource):
                    return

            if not cfg.CONF.convergence_engine:
                if (self.action, self.status) in (
                        (self.CREATE, self.IN_PROGRESS),
                        (self.UPDATE, self.IN_PROGRESS),
                        (self.ADOPT, self.IN_PROGRESS)):
                    exc = Exception(_('Resource update already requested'))
                    raise exception.ResourceFailure(exc, self, action)

            LOG.info(_LI('updating %s'), six.text_type(self))

            self.updated_time = datetime.utcnow()

            with self._action_recorder(action, exception.UpdateReplace):
                after_props.validate()

                tmpl_diff = self.update_template_diff(after.freeze(), before)
                if tmpl_diff and self.needs_replace_with_tmpl_diff(tmpl_diff):
                    raise exception.UpdateReplace(self)

                prop_diff = self.update_template_diff_properties(after_props,
                                                                 before_props)

                yield self.action_handler_task(action,
                                               args=[after, tmpl_diff,
                                                     prop_diff])
                self.t = after
                self.reparse()
                self._update_stored_properties()

        except exception.ResourceActionRestricted as ae:
            # catch all ResourceActionRestricted exceptions
            failure = exception.ResourceFailure(ae, self, action)
            self._add_event(action, self.FAILED, six.text_type(ae))
            raise failure
        except exception.UpdateReplace:
            # catch all UpdateReplace exceptions
            self._prepare_update_replace(action)
            raise

        yield self._break_if_required(
            self.UPDATE, environment.HOOK_POST_UPDATE)

    def prepare_for_replace(self):
        """Prepare resource for replacing.

        Some resources requires additional actions before replace them.
        If resource need to be changed before replacing, this method should
        be implemented in resource class.
        """
        pass

    def restore_prev_rsrc(self, convergence=False):
        """Restore resource after rollback.

        Some resources requires additional actions after rollback.
        If resource need to be changed during rollback, this method should
        be implemented in resource class.
        """
        pass

    def check(self):
        """Checks that the physical resource is in its expected state.

        Gets the current status of the physical resource and updates the
        database accordingly.  If check is not supported by the resource,
        default action is to fail and revert the resource's status to its
        original state with the added message that check was not performed.
        """
        action = self.CHECK
        LOG.info(_LI('Checking %s'), six.text_type(self))

        if hasattr(self, 'handle_%s' % action.lower()):
            return self._do_action(action)
        else:
            reason = '%s not supported for %s' % (action, self.type())
            self.state_set(action, self.COMPLETE, reason)

    def _verify_check_conditions(self, checks):
        def valid(check):
            if isinstance(check['expected'], list):
                return check['current'] in check['expected']
            else:
                return check['current'] == check['expected']

        msg = _("'%(attr)s': expected '%(expected)s', got '%(current)s'")
        invalid_checks = [
            msg % check
            for check in checks
            if not valid(check)
        ]
        if invalid_checks:
            raise exception.Error('; '.join(invalid_checks))

    def suspend(self):
        """Return a task to suspend the resource.

        Subclasses should provide a handle_suspend() method to implement
        suspend.
        """
        action = self.SUSPEND

        # Don't try to suspend the resource unless it's in a stable state
        # or if the previous suspend failed
        if (self.action == self.DELETE or
                (self.action != self.SUSPEND and
                 self.status != self.COMPLETE)):
            exc = exception.Error(_('State %s invalid for suspend')
                                  % six.text_type(self.state))
            raise exception.ResourceFailure(exc, self, action)

        LOG.info(_LI('suspending %s'), six.text_type(self))
        return self._do_action(action)

    def resume(self):
        """Return a task to resume the resource.

        Subclasses should provide a handle_resume() method to implement resume.
        """
        action = self.RESUME

        # Allow resume a resource if it's SUSPEND_COMPLETE
        # or RESUME_FAILED or RESUME_COMPLETE. Recommend to check
        # the real state of physical resource in handle_resume()
        if self.state not in ((self.SUSPEND, self.COMPLETE),
                              (self.RESUME, self.FAILED),
                              (self.RESUME, self.COMPLETE)):
            exc = exception.Error(_('State %s invalid for resume')
                                  % six.text_type(self.state))
            raise exception.ResourceFailure(exc, self, action)
        LOG.info(_LI('resuming %s'), six.text_type(self))
        return self._do_action(action)

    def snapshot(self):
        """Snapshot the resource and return the created data, if any."""
        LOG.info(_LI('snapshotting %s'), six.text_type(self))
        return self._do_action(self.SNAPSHOT)

    @scheduler.wrappertask
    def delete_snapshot(self, data):
        yield self.action_handler_task('delete_snapshot', args=[data])

    def physical_resource_name(self):
        if self.id is None or self.action == self.INIT:
            return None

        name = '%s-%s-%s' % (self.stack.name,
                             self.name,
                             short_id.get_id(self.uuid))

        if self.physical_resource_name_limit:
            name = self.reduce_physical_resource_name(
                name, self.physical_resource_name_limit)
        return name

    @staticmethod
    def reduce_physical_resource_name(name, limit):
        """Reduce length of physical resource name to a limit.

        The reduced name will consist of the following:

        * the first 2 characters of the name
        * a hyphen
        * the end of the name, truncated on the left to bring
          the name length within the limit

        :param name: The name to reduce the length of
        :param limit: The max length limit
        :returns: A name whose length is less than or equal to the limit
        """
        if len(name) <= limit:
            return name

        if limit < 4:
            raise ValueError(_('limit cannot be less than 4'))

        postfix_length = limit - 3
        return name[0:2] + '-' + name[-postfix_length:]

    def validate(self):
        """Validate the resource.

        This may be overridden by resource plugins to add extra
        validation logic specific to the resource implementation.
        """
        LOG.info(_LI('Validating %s'), six.text_type(self))
        return self.validate_template()

    def validate_template(self):
        """Validate structural/syntax aspects of the resource definition.

        Resource plugins should not override this, because this interface
        is expected to be called pre-create so things normally valid
        in an overridden validate() such as accessing properties
        may not work.
        """
        if self.stack.service_check_defer:
            self._validate_service_availability(
                self.stack.context,
                self.t.resource_type
            )

        function.validate(self.t)
        self.validate_deletion_policy(self.t.deletion_policy())
        self.t.update_policy(self.update_policy_schema,
                             self.context).validate()
        try:
            validate = self.properties.validate(
                with_value=self.stack.strict_validate)
        except exception.StackValidationFailed as ex:
            path = [self.stack.t.RESOURCES, ex.path[0],
                    self.stack.t.get_section_name(ex.path[1])]
            path.extend(ex.path[2:])
            raise exception.StackValidationFailed(
                error=ex.error,
                path=path,
                message=ex.error_message)
        return validate

    @classmethod
    def validate_deletion_policy(cls, policy):
        if policy not in rsrc_defn.ResourceDefinition.DELETION_POLICIES:
            msg = _('Invalid deletion policy "%s"') % policy
            raise exception.StackValidationFailed(message=msg)

        if policy == rsrc_defn.ResourceDefinition.SNAPSHOT:
            if not callable(getattr(cls, 'handle_snapshot_delete', None)):
                msg = _('"%s" deletion policy not supported') % policy
                raise exception.StackValidationFailed(message=msg)

    def _update_replacement_data(self, template_id):
        # Update the replacement resource's needed_by and replaces
        # fields. Make sure that the replacement belongs to the given
        # template and there is no engine working on it.
        if self.replaced_by is None:
            return

        try:
            db_res = resource_objects.Resource.get_obj(
                self.context, self.replaced_by)
        except exception.NotFound:
            LOG.info(_LI("Could not find replacement of resource %(name)s "
                         "with id %(id)s while updating needed_by."),
                     {'name': self.name, 'id': self.replaced_by})
            return

        if (db_res.current_template_id == template_id):
                # Following update failure is ignorable; another
                # update might have locked/updated the resource.
                db_res.select_and_update(
                    {'needed_by': self.needed_by,
                     'replaces': None},
                    atomic_key=db_res.atomic_key,
                    expected_engine_id=None
                )

    def delete_convergence(self, template_id, input_data, engine_id, timeout):
        """Destroys the resource if it doesn't belong to given template.

        The given template is suppose to be the current template being
        provisioned.

        Also, since this resource is visited as part of clean-up phase,
        the needed_by should be updated. If this resource was
        replaced by more recent resource, then delete this and update
        the replacement resource's needed_by and replaces fields.
        """
        self._acquire(engine_id)
        try:
            self.needed_by = list(set(v for v in input_data.values()
                                      if v is not None))

            if self.current_template_id != template_id:
                runner = scheduler.TaskRunner(self.destroy)
                runner(timeout=timeout)

                # update needed_by and replaces of replacement resource
                self._update_replacement_data(template_id)
            else:
                self._release(engine_id)
        except:  # noqa
            with excutils.save_and_reraise_exception():
                self._release(engine_id)

    def handle_delete(self):
        """Default implementation; should be overridden by resources."""
        if self.entity and self.resource_id is not None:
            try:
                obj = getattr(self.client(), self.entity)
                obj.delete(self.resource_id)
            except Exception as ex:
                self.client_plugin().ignore_not_found(ex)
                return None
            return self.resource_id

    @scheduler.wrappertask
    def delete(self):
        """A task to delete the resource.

        Subclasses should provide a handle_delete() method to customise
        deletion.
        """
        action = self.DELETE

        if (self.action, self.status) == (self.DELETE, self.COMPLETE):
            return
        # No need to delete if the resource has never been created
        if self.action == self.INIT:
            return

        initial_state = self.state

        # This method can be called when we replace a resource, too. In that
        # case, a hook has already been dealt with in `Resource.update` so we
        # shouldn't do it here again:
        if self.stack.action == self.stack.DELETE:
            yield self._break_if_required(
                self.DELETE, environment.HOOK_PRE_DELETE)

        LOG.info(_LI('deleting %s'), six.text_type(self))

        if self._stored_properties_data is not None:
            # On delete we can't rely on re-resolving the properties
            # so use the stored frozen_definition instead
            self.properties = self.frozen_definition().properties(
                self.properties_schema, self.context)

        with self._action_recorder(action):
            if self.abandon_in_progress:
                deletion_policy = self.t.RETAIN
            else:
                deletion_policy = self.t.deletion_policy()

            if deletion_policy != self.t.RETAIN:
                if deletion_policy == self.t.SNAPSHOT:
                    action_args = [[initial_state], 'snapshot']
                else:
                    action_args = []
                yield self.action_handler_task(action, *action_args)

        if self.stack.action == self.stack.DELETE:
            yield self._break_if_required(
                self.DELETE, environment.HOOK_POST_DELETE)

    @scheduler.wrappertask
    def destroy(self):
        """A task to delete the resource and remove it from the database."""
        yield self.delete()

        if self.id is None:
            return

        try:
            resource_objects.Resource.delete(self.context, self.id)
        except exception.NotFound:
            # Don't fail on delete if the db entry has
            # not been created yet.
            pass

        self.id = None

    def resource_id_set(self, inst):
        self.resource_id = inst
        if self.id is not None:
            try:
                resource_objects.Resource.update_by_id(
                    self.context,
                    self.id,
                    {'physical_resource_id': self.resource_id})
            except Exception as ex:
                LOG.warning(_LW('db error %s'), ex)

    def _store(self, metadata=None):
        """Create the resource in the database."""

        properties_data_encrypted, properties_data = (
            resource_objects.Resource.encrypt_properties_data(
                self._stored_properties_data))
        if not self.root_stack_id:
            self.root_stack_id = self.stack.root_stack_id()
        try:
            rs = {'action': self.action,
                  'status': self.status,
                  'status_reason': self.status_reason,
                  'stack_id': self.stack.id,
                  'physical_resource_id': self.resource_id,
                  'name': self.name,
                  'rsrc_metadata': metadata,
                  'properties_data': properties_data,
                  'properties_data_encrypted': properties_data_encrypted,
                  'needed_by': self.needed_by,
                  'requires': self.requires,
                  'replaces': self.replaces,
                  'replaced_by': self.replaced_by,
                  'current_template_id': self.current_template_id,
                  'stack_name': self.stack.name,
                  'root_stack_id': self.root_stack_id}

            new_rs = resource_objects.Resource.create(self.context, rs)
            self.id = new_rs.id
            self.uuid = new_rs.uuid
            self.created_time = new_rs.created_at
            self._rsrc_metadata = metadata
        except Exception as ex:
            LOG.error(_LE('DB error %s'), ex)

    def _add_event(self, action, status, reason):
        """Add a state change event to the database."""
        ev = event.Event(self.context, self.stack, action, status, reason,
                         self.resource_id, self.properties,
                         self.name, self.type())

        ev.store()
        self.stack.dispatch_event(ev)

    def _store_or_update(self, action, status, reason):
        prev_action = self.action
        self.action = action
        self.status = status
        self.status_reason = reason

        properties_data_encrypted, properties_data = (
            resource_objects.Resource.encrypt_properties_data(
                self._stored_properties_data))
        data = {
            'action': self.action,
            'status': self.status,
            'status_reason': reason,
            'stack_id': self.stack.id,
            'updated_at': self.updated_time,
            'properties_data': properties_data,
            'properties_data_encrypted': properties_data_encrypted,
            'needed_by': self.needed_by,
            'requires': self.requires,
            'replaces': self.replaces,
            'replaced_by': self.replaced_by,
            'current_template_id': self.current_template_id,
            'physical_resource_id': self.resource_id,
            'root_stack_id': self.root_stack_id
        }
        if prev_action == self.INIT:
            metadata = self.t.metadata()
            data['rsrc_metadata'] = metadata
        else:
            metadata = self._rsrc_metadata

        if self.id is not None:
            try:
                resource_objects.Resource.update_by_id(self.context, self.id,
                                                       data)
            except Exception as ex:
                LOG.error(_LE('DB error %s'), ex)
            else:
                self._rsrc_metadata = metadata
        else:
            # This should only happen in unit tests
            LOG.warning(_LW('Resource "%s" not pre-stored in DB'), self)
            self._store(metadata)

    @contextlib.contextmanager
    def lock(self, engine_id):
        self._acquire(engine_id)
        try:
            yield
        except:  # noqa
            with excutils.save_and_reraise_exception():
                self._release(engine_id)
        else:
            self._release(engine_id)

    def _acquire(self, engine_id):
        updated_ok = False
        try:
            rs = resource_objects.Resource.get_obj(self.context, self.id)
            updated_ok = rs.select_and_update(
                {'engine_id': engine_id},
                atomic_key=rs.atomic_key,
                expected_engine_id=None)
        except Exception as ex:
            LOG.error(_LE('DB error %s'), ex)
            raise

        if not updated_ok:
            ex = exception.UpdateInProgress(self.name)
            LOG.error(_LE(
                'Error acquiring lock for resource id:%(resource_id)s with '
                'atomic_key:%(atomic_key)s, '
                'engine_id:%(rs_engine_id)s/%(engine_id)s') % {
                    'resource_id': rs.id, 'atomic_key': rs.atomic_key,
                    'rs_engine_id': rs.engine_id, 'engine_id': engine_id})
            raise ex

    def _release(self, engine_id):
        rs = None
        try:
            rs = resource_objects.Resource.get_obj(self.context, self.id)
        except (exception.NotFound, exception.EntityNotFound):
            # ignore: Resource is deleted holding a lock-on
            return

        atomic_key = rs.atomic_key
        if atomic_key is None:
            atomic_key = 0

        updated_ok = rs.select_and_update(
            {'engine_id': None,
             'current_template_id': self.current_template_id,
             'updated_at': self.updated_time,
             'requires': self.requires,
             'needed_by': self.needed_by},
            expected_engine_id=engine_id,
            atomic_key=atomic_key)

        if not updated_ok:
            LOG.warning(_LW('Failed to unlock resource %s'), self.name)

    def _resolve_all_attributes(self, attr):
        """Method for resolving all attributes.

        This method uses basic _resolve_attribute method for resolving
        specific attributes. Base attributes will be resolved with
        corresponding method, which should be defined in each resource
        class.

        :param attr: attribute name, which will be resolved
        :returns: method of resource class, which resolve base attribute
        """
        if attr in self.base_attributes_schema:
            # check resource_id, because usually it is required for getting
            # information about resource
            if not self.resource_id:
                return None
            try:
                return getattr(self, '_{0}_resource'.format(attr))()
            except Exception as ex:
                self.client_plugin().ignore_not_found(ex)
                return None
        else:
            try:
                return self._resolve_attribute(attr)
            except Exception as ex:
                self.client_plugin().ignore_not_found(ex)
                return None

    def _show_resource(self):
        """Default implementation; should be overridden by resources.

        :returns: the map of resource information or None
        """
        if self.entity:
            try:
                obj = getattr(self.client(), self.entity)
                resource = obj.get(self.resource_id)
                return resource.to_dict()
            except AttributeError as ex:
                LOG.warning(_LW("Resolving 'show' attribute has failed : %s"),
                            ex)
                return None

    def get_live_resource_data(self):
        """Default implementation; can be overridden by resources.

        Get resource data and handle it with exceptions.
        """
        try:
            resource_data = self._show_resource()
        except Exception as ex:
            if self.client_plugin().is_not_found(ex):
                raise exception.EntityNotFound(
                    entity='Resource', name=self.name)
            raise
        return resource_data

    def parse_live_resource_data(self, resource_properties, resource_data):
        """Default implementation; can be overridden by resources.

        Parse resource data for using it in updating properties with live
        state.
        :param resource_properties: properties of stored resource plugin.
        :param resource_data: data from current live state of a resource.
        """
        return {}

    def get_live_state(self, resource_properties):
        """Default implementation; should be overridden by resources.

        :param resource_properties: resource's object of Properties class.
        :returns: dict of resource's real state of properties.
        """
        resource_data = self.get_live_resource_data()
        if resource_data is None:
            return {}
        return self.parse_live_resource_data(resource_properties,
                                             resource_data)

    def _update_properties_with_live_state(self, resource_properties,
                                           live_properties):
        """Update resource properties data with live state properties.

        Note, that live_properties can contains None values, so there's next
        situation: property equals to some value, but live state has no such
        property, i.e. property equals to None, so during update property
        should be updated with None.
        """
        for key in resource_properties:
            if key in live_properties:
                if resource_properties.get(key) != live_properties.get(key):
                    resource_properties.data.update(
                        {key: live_properties.get(key)})

    def _resolve_attribute(self, name):
        """Default implementation of resolving resource's attributes.

        Should be overridden by resources, that expose attributes.

        :param name: The attribute to resolve
        :returns: the resource attribute named key
        """
        # By default, no attributes resolve
        pass

    def regenerate_info_schema(self, definition):
        """Default implementation; should be overridden by resources.

        Should be overridden by resources that would require schema refresh
        during update, ex. TemplateResource.

        :definition: Resource Definition
        """
        # By default, do not regenerate
        pass

    def state_reset(self):
        """Reset state to (INIT, COMPLETE)."""
        self.action = self.INIT
        self.status = self.COMPLETE

    def state_set(self, action, status, reason="state changed"):
        if action not in self.ACTIONS:
            raise ValueError(_("Invalid action %s") % action)

        if status not in self.STATUSES:
            raise ValueError(_("Invalid status %s") % status)

        old_state = (self.action, self.status)
        new_state = (action, status)
        self._store_or_update(action, status, reason)

        if new_state != old_state:
            self._add_event(action, status, reason)

        self.stack.reset_resource_attributes()

    @property
    def state(self):
        """Returns state, tuple of action, status."""
        return (self.action, self.status)

    def get_reference_id(self):
        """Default implementation for function get_resource.

        This may be overridden by resource plugins to add extra
        logic specific to the resource implementation.
        """
        if self.resource_id is not None:
            return six.text_type(self.resource_id)
        else:
            return six.text_type(self.name)

    def FnGetRefId(self):
        """For the intrinsic function Ref.

        :results: the id or name of the resource.
        """
        if self.stack.has_cache_data(self.name):
            return self.stack.cache_data_reference_id(self.name)
        return self.get_reference_id()

    def physical_resource_name_or_FnGetRefId(self):
        res_name = self.physical_resource_name()
        if res_name is not None:
            return six.text_type(res_name)
        else:
            return Resource.get_reference_id(self)

    def get_attribute(self, key, *path):
        """Default implementation for function get_attr and Fn::GetAtt.

        This may be overridden by resource plugins to add extra
        logic specific to the resource implementation.
        """
        try:
            attribute = self.attributes[key]
        except KeyError:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        return attributes.select_from_attribute(attribute, path)

    def FnGetAtt(self, key, *path):
        """For the intrinsic function Fn::GetAtt.

        :param key: the attribute key.
        :param path: a list of path components to select from the attribute.
        :returns: the attribute value.
        """
        if self.stack.has_cache_data(self.name):
            # Load from cache for lightweight resources.
            complex_key = key
            if path:
                complex_key = tuple([key] + list(path))
            attribute = self.stack.cache_data_resource_attribute(
                self.name, complex_key)
            return attribute
        return self.get_attribute(key, *path)

    def FnGetAtts(self):
        """For the intrinsic function get_attr which returns all attributes.

        :returns: dict of all resource's attributes exclude "show" attribute.
        """
        if self.stack.has_cache_data(self.name):
            attrs = self.stack.cache_data_resource_all_attributes(self.name)
        else:
            attrs = dict((k, v) for k, v in six.iteritems(self.attributes))
        attrs = dict((k, v) for k, v in six.iteritems(attrs)
                     if k != self.SHOW)
        return attrs

    def FnBase64(self, data):
        """For the intrinsic function Fn::Base64.

        :param data: the input data.
        :returns: the Base64 representation of the input data.
        """
        return base64.b64encode(data)

    def _signal_check_action(self):
        if self.action in self.no_signal_actions:
            self._add_event(self.action, self.status,
                            'Cannot signal resource during %s' % self.action)
            msg = _('Signal resource during %s') % self.action
            raise exception.NotSupported(feature=msg)

    def _signal_check_hook(self, details):
        if details and 'unset_hook' in details:
            hook = details['unset_hook']
            if not environment.valid_hook_type(hook):
                msg = (_('Invalid hook type "%(hook)s" for %(resource)s') %
                       {'hook': hook, 'resource': six.text_type(self)})
                raise exception.InvalidBreakPointHook(message=msg)

            if not self.has_hook(hook):
                msg = (_('The "%(hook)s" hook is not defined '
                         'on %(resource)s') %
                       {'hook': hook, 'resource': six.text_type(self)})
                raise exception.InvalidBreakPointHook(message=msg)

    def _unset_hook(self, details):
        # Clear the hook without interfering with resources'
        # `handle_signal` callbacks:
        hook = details['unset_hook']
        self.clear_hook(hook)
        LOG.info(_LI('Clearing %(hook)s hook on %(resource)s'),
                 {'hook': hook, 'resource': six.text_type(self)})
        self._add_event(self.action, self.status,
                        "Hook %s is cleared" % hook)

    def _handle_signal(self, details):
        if not callable(getattr(self, 'handle_signal', None)):
            raise exception.ResourceActionNotSupported(action='signal')

        def get_string_details():
            if details is None:
                return 'No signal details provided'
            if isinstance(details, six.string_types):
                return details
            if isinstance(details, dict):
                if all(k in details for k in ('previous', 'current',
                                              'reason')):
                    # this is from Ceilometer.
                    auto = '%(previous)s to %(current)s (%(reason)s)' % details
                    return 'alarm state changed from %s' % auto
                elif 'state' in details:
                    # this is from watchrule
                    return 'alarm state changed to %(state)s' % details

            return 'Unknown'

        try:
            signal_result = self.handle_signal(details)
            if signal_result:
                reason_string = "Signal: %s" % signal_result
            else:
                reason_string = get_string_details()
            self._add_event('SIGNAL', self.status, reason_string)
        except exception.NoActionRequired:
            # Don't log an event as it just spams the user.
            pass
        except Exception as ex:
            LOG.info(_LI('signal %(name)s : %(msg)s'),
                     {'name': six.text_type(self), 'msg': ex},
                     exc_info=True)
            failure = exception.ResourceFailure(ex, self)
            raise failure

    def signal(self, details=None, need_check=True):
        """Signal the resource.

        Returns True if the metadata for all resources in the stack needs to
        be regenerated as a result of the signal, False if it should not be.

        Subclasses should provide a handle_signal() method to implement the
        signal. The base-class raise an exception if no handler is implemented.
        """
        if need_check:
            self._signal_check_action()
            self._signal_check_hook(details)
        if details and 'unset_hook' in details:
            self._unset_hook(details)
            return False
        self._handle_signal(details)
        return self.signal_needs_metadata_updates

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            raise exception.UpdateReplace(self.name)

    def metadata_update(self, new_metadata=None):
        """No-op for resources which don't explicitly override this method."""
        if new_metadata:
            LOG.warning(_LW("Resource %s does not implement metadata update"),
                        self.name)

    @classmethod
    def resource_to_template(cls, resource_type, template_type='cfn'):
        """Generate a provider template that mirrors the resource.

        :param resource_type: The resource type to be displayed in the template
        :param template_type: the template type to generate, cfn or hot.
        :returns: A template where the resource's properties_schema is mapped
            as parameters, and the resource's attributes_schema is mapped as
            outputs
        """
        schema = cls.properties_schema
        params, props = (properties.Properties.
                         schema_to_parameters_and_properties(schema,
                                                             template_type))
        resource_name = cls.__name__
        outputs = attributes.Attributes.as_outputs(resource_name, cls,
                                                   template_type)
        description = 'Initial template of %s' % resource_name
        return cls.build_template_dict(resource_name, resource_type,
                                       template_type, params, props,
                                       outputs, description)

    @staticmethod
    def build_template_dict(res_name, res_type, tmpl_type,
                            params, props, outputs, description):
        if tmpl_type == 'hot':
            tmpl_dict = {
                hot_tmpl.HOTemplate20150430.VERSION: '2015-04-30',
                hot_tmpl.HOTemplate20150430.DESCRIPTION: description,
                hot_tmpl.HOTemplate20150430.PARAMETERS: params,
                hot_tmpl.HOTemplate20150430.OUTPUTS: outputs,
                hot_tmpl.HOTemplate20150430.RESOURCES: {
                    res_name: {
                        hot_tmpl.RES_TYPE: res_type,
                        hot_tmpl.RES_PROPERTIES: props}}}
        else:
            tmpl_dict = {
                cfn_tmpl.CfnTemplate.ALTERNATE_VERSION: '2012-12-12',
                cfn_tmpl.CfnTemplate.DESCRIPTION: description,
                cfn_tmpl.CfnTemplate.PARAMETERS: params,
                cfn_tmpl.CfnTemplate.RESOURCES: {
                    res_name: {
                        cfn_tmpl.RES_TYPE: res_type,
                        cfn_tmpl.RES_PROPERTIES: props}
                },
                cfn_tmpl.CfnTemplate.OUTPUTS: outputs}

        return tmpl_dict

    def data(self):
        """Return the resource data for this resource.

        Use methods data_set and data_delete to modify the resource data
        for this resource.

        :returns: a dict representing the resource data for this resource.
        """
        if self._data is None and self.id:
            try:
                self._data = resource_data_objects.ResourceData.get_all(self)
            except exception.NotFound:
                pass

        return self._data or {}

    def data_set(self, key, value, redact=False):
        """Set a key in the resource data."""
        resource_data_objects.ResourceData.set(self, key, value, redact)
        # force fetch all resource data from the database again
        self._data = None

    def data_delete(self, key):
        """Remove a key from the resource data.

        :returns: True if the key existed to delete.
        """
        try:
            resource_data_objects.ResourceData.delete(self, key)
        except exception.NotFound:
            return False
        else:
            # force fetch all resource data from the database again
            self._data = None
            return True

    def is_using_neutron(self):
        try:
            self.client('neutron')
        except Exception:
            return False
        else:
            return True
