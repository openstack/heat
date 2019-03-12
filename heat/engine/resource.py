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
import contextlib
import datetime as dt
import itertools
import pydoc
import tenacity
import weakref

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import reflection
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common import identifier
from heat.common import short_id
from heat.common import timeutils
from heat.engine import attributes
from heat.engine.cfn import template as cfn_tmpl
from heat.engine import clients
from heat.engine.clients import default_client_plugin
from heat.engine import environment
from heat.engine import event
from heat.engine import function
from heat.engine.hot import template as hot_tmpl
from heat.engine import node_data
from heat.engine import properties
from heat.engine import resources
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import status
from heat.engine import support
from heat.engine import sync_point
from heat.engine import template
from heat.objects import resource as resource_objects
from heat.objects import resource_data as resource_data_objects
from heat.objects import resource_properties_data as rpd_objects
from heat.rpc import client as rpc_client

cfg.CONF.import_opt('action_retry_limit', 'heat.common.config')
cfg.CONF.import_opt('observe_on_update', 'heat.common.config')
cfg.CONF.import_opt('error_wait_time', 'heat.common.config')

LOG = logging.getLogger(__name__)

datetime = dt.datetime


def _register_class(resource_type, resource_class):
    resources.global_env().register_class(resource_type, resource_class)


# Attention developers about to move/delete this: STOP IT!!!
UpdateReplace = exception.UpdateReplace


# Attention developers about to move this: STOP IT!!!
class NoActionRequired(Exception):
    """Exception raised when a signal is ignored.

    Resource subclasses should raise this exception from handle_signal() to
    suppress recording of an event corresponding to the signal.
    """
    def __init__(self, res_name='Unknown', reason=''):
        msg = (_("The resource %(res)s could not perform "
                 "scaling action: %(reason)s") %
               {'res': res_name, 'reason': reason})
        super(Exception, self).__init__(six.text_type(msg))


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
class Resource(status.ResourceStatus):
    BASE_ATTRIBUTES = (SHOW, ) = (attributes.SHOW_ATTR, )

    LOCK_ACTIONS = (
        LOCK_NONE, LOCK_ACQUIRE, LOCK_RELEASE, LOCK_RESPECT,
    ) = (
        None, 1, -1, 0,
    )

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
            cache_mode=attributes.Schema.CACHE_NONE,
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
    no_signal_actions = (status.ResourceStatus.SUSPEND,
                         status.ResourceStatus.DELETE)

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

        return super(Resource, cls).__new__(ResourceClass)

    @classmethod
    def _validate_service_availability(cls, context, resource_type):
        try:
            (svc_available, reason) = cls.is_service_available(context)
        except Exception as exc:
            LOG.exception("Resource type %s unavailable",
                          resource_type)
            ex = exception.ResourceTypeUnavailable(
                resource_type=resource_type,
                service_name=cls.default_client_name,
                reason=six.text_type(exc))
            raise ex
        else:
            if not svc_available:
                ex = exception.ResourceTypeUnavailable(
                    resource_type=resource_type,
                    service_name=cls.default_client_name,
                    reason=reason)
                LOG.info(six.text_type(ex))
                raise ex

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
        self.reparse(client_resolve=False)
        self.update_policy = self.t.update_policy(self.update_policy_schema,
                                                  self.context)
        self._update_allowed_properties = self.calc_update_allowed(
            self.properties)
        self.attributes_schema.update(self.base_attributes_schema)
        self.attributes = attributes.Attributes(self.name,
                                                self.attributes_schema,
                                                self._make_resolver(
                                                    weakref.ref(self)))

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
        self._attr_data_id = None
        self._rsrc_metadata = None
        self._rsrc_prop_data_id = None
        self._stored_properties_data = None
        self.created_time = stack.created_time
        self.updated_time = stack.updated_time
        self._rpc_client = None
        self.requires = set()
        self.replaces = None
        self.replaced_by = None
        self.current_template_id = None
        self.old_template_id = None
        self.root_stack_id = None
        self._calling_engine_id = None
        self._atomic_key = None
        self.converge = False

        if not self.stack.in_convergence_check:
            resource = stack.db_resource_get(name)
            if resource:
                self._load_data(resource)
        else:
            proxy = self.stack.defn[self.name]
            node_data = proxy._resource_data
            if node_data is not None:
                self.action, self.status = proxy.state
                self.id = node_data.primary_key
                self.uuid = node_data.uuid

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
        self.attributes.cached_attrs = resource.attr_data or None
        self._attr_data_id = resource.attr_data_id
        self._rsrc_metadata = resource.rsrc_metadata
        self._stored_properties_data = resource.properties_data
        self._rsrc_prop_data_id = resource.rsrc_prop_data_id
        self.created_time = resource.created_at
        self.updated_time = resource.updated_at
        self.requires = set(resource.requires)
        self.replaces = resource.replaces
        self.replaced_by = resource.replaced_by
        self.current_template_id = resource.current_template_id
        self.root_stack_id = resource.root_stack_id
        self._atomic_key = resource.atomic_key

    @property
    def external_id(self):
        return self.t.external_id()

    @classmethod
    def getdoc(cls):
        if cls.__doc__ is None:
            return _('No description available')
        return pydoc.getdoc(cls)

    @property
    def stack(self):
        stack = self._stackref()
        assert stack is not None, "Need a reference to the Stack object"
        return stack

    @stack.setter
    def stack(self, stack):
        self._stackref = weakref.ref(stack)

    @classmethod
    def load(cls, context, resource_id, current_traversal, is_update, data):
        """Load a specified resource from the database to check.

        Returns a tuple of the Resource, the StackDefinition corresponding to
        the resource's ResourceDefinition (i.e. the one the resource was last
        updated to if it has already been created, or the one it will be
        created with if it hasn't been already), and the Stack containing the
        latest StackDefinition (i.e. the one that the latest traversal is
        updating to.

        The latter two must remain in-scope, because the Resource holds weak
        references to them.
        """
        from heat.engine import stack as stack_mod
        db_res = resource_objects.Resource.get_obj(context, resource_id)
        curr_stack = stack_mod.Stack.load(context, stack_id=db_res.stack_id,
                                          cache_data=data)

        initial_stk_defn = latest_stk_defn = curr_stack.defn

        current_template_id = db_res.current_template_id
        using_new_template = (current_template_id != curr_stack.t.id and
                              current_template_id is not None)
        will_create = (db_res.action == cls.INIT and
                       is_update and
                       current_traversal == curr_stack.current_traversal)
        if using_new_template and not will_create:
            # load the definition associated with the resource's template
            current_template = template.Template.load(context,
                                                      current_template_id)
            initial_stk_defn = curr_stack.defn.clone_with_new_template(
                current_template,
                curr_stack.identifier())
            curr_stack.defn = initial_stk_defn

        res_defn = initial_stk_defn.resource_definition(db_res.name)
        res_type = initial_stk_defn.env.registry.get_class_to_instantiate(
            res_defn.resource_type, resource_name=db_res.name)

        # If the resource type has changed and the new one is a valid
        # substitution, use that as the class to instantiate.
        if is_update and (latest_stk_defn is not initial_stk_defn):
            try:
                new_res_defn = latest_stk_defn.resource_definition(db_res.name)
            except KeyError:
                pass
            else:
                new_registry = latest_stk_defn.env.registry
                new_res_type = new_registry.get_class_to_instantiate(
                    new_res_defn.resource_type, resource_name=db_res.name)

                if res_type.check_is_substituted(new_res_type):
                    res_type = new_res_type

        # Load only the resource in question; don't load all resources
        # by invoking stack.resources. Maintain light-weight stack.
        resource = res_type(db_res.name, res_defn, curr_stack)
        resource._load_data(db_res)

        curr_stack.defn = latest_stk_defn
        return resource, initial_stk_defn, curr_stack

    def make_replacement(self, new_tmpl_id, requires):
        """Create a replacement resource in the database.

        Returns the DB ID of the new resource, or None if the new resource
        cannot be created (generally because the template ID does not exist).
        Raises UpdateInProgress if another traversal has already locked the
        current resource.
        """
        # 1. create the replacement with "replaces" = self.id
        # Don't set physical_resource_id so that a create is triggered.
        rs = {'stack_id': self.stack.id,
              'name': self.name,
              'rsrc_prop_data_id': None,
              'needed_by': [],
              'requires': sorted(requires, reverse=True),
              'replaces': self.id,
              'action': self.INIT,
              'status': self.COMPLETE,
              'current_template_id': new_tmpl_id,
              'stack_name': self.stack.name,
              'root_stack_id': self.root_stack_id}
        update_data = {'status': self.COMPLETE}

        # Retry in case a signal has updated the atomic_key
        attempts = max(cfg.CONF.client_retry_limit, 0) + 1

        def prepare_attempt(fn, attempt):
            if attempt > 1:
                res_obj = resource_objects.Resource.get_obj(
                    self.context, self.id)
                if (res_obj.engine_id is not None or
                        res_obj.updated_at != self.updated_time):
                    raise exception.UpdateInProgress(resource_name=self.name)
                self._atomic_key = res_obj.atomic_key

        @tenacity.retry(
            stop=tenacity.stop_after_attempt(attempts),
            retry=tenacity.retry_if_exception_type(
                exception.UpdateInProgress),
            before=prepare_attempt,
            wait=tenacity.wait_random(max=2),
            reraise=True)
        def create_replacement():
            return resource_objects.Resource.replacement(self.context,
                                                         self.id,
                                                         update_data,
                                                         rs,
                                                         self._atomic_key)

        new_rs = create_replacement()
        if new_rs is None:
            return None
        self._incr_atomic_key(self._atomic_key)
        self.replaced_by = new_rs.id
        return new_rs.id

    def reparse(self, client_resolve=True):
        """Reparse the resource properties.

        Optional translate flag for property translation and
        client_resolve flag for resolving properties by doing
        client lookup.
        """
        self.properties = self.t.properties(self.properties_schema,
                                            self.context)
        self.translate_properties(self.properties, client_resolve)

    def calc_update_allowed(self, props):
        update_allowed_set = set(self.update_allowed_properties)
        for (psk, psv) in six.iteritems(props.props):
            if psv.update_allowed():
                update_allowed_set.add(psk)
        return update_allowed_set

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
        rs = resource_objects.Resource.get_obj(self.stack.context, self.id,
                                               refresh=True,
                                               fields=('rsrc_metadata', ))
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
        refresh = merge_metadata is not None
        db_res = resource_objects.Resource.get_obj(
            self.stack.context, self.id, refresh=refresh,
            fields=('name', 'rsrc_metadata', 'atomic_key', 'engine_id',
                    'action', 'status'))
        if db_res.action == self.DELETE:
            self._db_res_is_deleted = True
            LOG.debug("resource %(name)s, id: %(id)s is DELETE_%(st)s, "
                      "not setting metadata",
                      {'name': self.name, 'id': self.id, 'st': db_res.status})
            raise exception.ResourceNotAvailable(resource_name=self.name)
        LOG.debug('Setting metadata for %s', six.text_type(self))
        if refresh:
            metadata = merge_metadata(metadata, db_res.rsrc_metadata)
        if db_res.update_metadata(metadata):
            self._incr_atomic_key(db_res.atomic_key)
        self._rsrc_metadata = metadata

    def handle_metadata_reset(self):
        """Default implementation; should be overridden by resources.

        Now we override this method to reset the metadata for scale-policy
        and scale-group resources, because their metadata might hang in a
        wrong state ('scaling_in_progress' is always True) if engine restarts
        while scaling.
        """
        pass

    def _break_if_required(self, action, hook):
        """Block the resource until the hook is cleared if there is one."""
        if self.stack.env.registry.matches_hook(self.name, hook):
            self.trigger_hook(hook)
            self._add_event(self.action, self.status,
                            "%(a)s paused until Hook %(h)s is cleared"
                            % {'a': action, 'h': hook})
            LOG.info('Reached hook on %s', self)

            while self.has_hook(hook):
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
        """Return True if the resource has an existing nested stack.

        For most resource types, this will always return False. StackResource
        subclasses return True when appropriate. Resource subclasses that may
        return True must also provide a nested_identifier() method to return
        the identifier of the nested stack, and a nested() method to return a
        Stack object for the nested stack.
        """
        return False

    def get_nested_parameters_stack(self):
        """Return the nested stack for schema validation.

        Regular resources don't have such a thing.
        """
        return

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

    def frozen_definition(self):
        """Return a frozen ResourceDefinition with stored property values.

        The returned definition will contain the property values read from the
        database, and will have all intrinsic functions resolved (note that
        this makes it useless for calculating dependencies).
        """
        if self._stored_properties_data is not None:
            args = {'properties': self._stored_properties_data}
        else:
            args = {}
        return self.t.freeze(**args)

    @contextlib.contextmanager
    def frozen_properties(self):
        """Context manager to use the frozen property values from the database.

        The live property values are always substituted back when the context
        ends.
        """
        live_props = self.properties
        props = self.frozen_definition().properties(self.properties_schema,
                                                    self.context)

        try:
            self.properties = props
            yield props
        finally:
            self.properties = live_props

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
        update_allowed_set = self.calc_update_allowed(after_props)
        immutable_set = set()
        for (psk, psv) in six.iteritems(after_props.props):
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
                LOG.warning('Ignoring error in old property value '
                            '%(prop_name)s: %(msg)s',
                            {'prop_name': key, 'msg': six.text_type(exc)})
                return True

            return before != after_props.get(key)

        # Create a set of keys which differ (or are missing/added)
        changed_properties_set = set(k for k in after_props if prop_changed(k))

        # Create a list of updated properties offending property immutability
        update_replace_forbidden = [k for k in changed_properties_set
                                    if k in immutable_set]

        if update_replace_forbidden:
            msg = _("Update to properties %(props)s of %(name)s (%(res)s)"
                    ) % {'props': ", ".join(sorted(update_replace_forbidden)),
                         'res': self.type(), 'name': self.name}
            raise exception.NotSupported(feature=msg)

        if changed_properties_set and self.needs_replace_with_prop_diff(
                changed_properties_set,
                after_props,
                before_props):
            raise UpdateReplace(self)

        if not changed_properties_set.issubset(update_allowed_set):
            raise UpdateReplace(self.name)

        return dict((k, after_props.get(k)) for k in changed_properties_set)

    def __str__(self):
        class_name = reflection.get_class_name(self, fully_qualified=False)
        if self.stack.id is not None:
            if self.resource_id is not None:
                text = '%s "%s" [%s] %s' % (class_name, self.name,
                                            self.resource_id,
                                            six.text_type(self.stack))
            else:
                text = '%s "%s" %s' % (class_name, self.name,
                                       six.text_type(self.stack))
        else:
            text = '%s "%s"' % (class_name, self.name)
        return six.text_type(text)

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
        try:
            reqd_by = self.stack.dependencies.required_by(self)
        except KeyError:
            if self.stack.convergence:
                # for convergence, fall back to building from node graph
                needed_by_ids = self.stack.dependent_resource_ids(self.id)
                reqd_by = [r for r in self.stack.resources.values()
                           if r.id in needed_by_ids]
            else:
                LOG.error('Getting required_by list for Resource not in '
                          'dependency graph.')
                return []
        return [r.name for r in reqd_by]

    def client(self, name=None, version=None):
        client_name = name or self.default_client_name
        assert client_name, "Must specify client name"
        return self.stack.clients.client(client_name, version)

    def client_plugin(self, name=None):
        client_name = name or self.default_client_name
        assert client_name, "Must specify client name"
        return self.stack.clients.client_plugin(client_name)

    def _default_client_plugin(self):
        """Always return a client plugin.

        This will be the client_plugin if the resource has defined a
        default_client_name, or a no-op plugin if it does not. Thus, the
        result of this call always has e.g. is_not_found() and is_conflict()
        methods.
        """
        cp = None
        if self.default_client_name:
            cp = self.client_plugin()
        if cp is None:
            cp = default_client_plugin.DefaultClientPlugin(self.context)
        return cp

    @classmethod
    def is_service_available(cls, context):
        # NOTE(kanagaraj-manickam): return True to satisfy the cases like
        # resource does not have endpoint, such as RandomString, OS::Heat
        # resources as they are implemented within the engine.
        if cls.default_client_name is None:
            return (True, None)
        client_plugin = clients.Clients(context).client_plugin(
            cls.default_client_name)

        if not client_plugin:
            raise exception.ClientNotAvailable(
                client_name=cls.default_client_name)

        service_types = client_plugin.service_types
        if not service_types:
            return (True, None)

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
                    return (True, None)
                else:
                    reason = _('Required extension {0} in {1} service '
                               'is not available.')
                    reason = reason.format(req_extension,
                                           cls.default_client_name)
            else:
                reason = _('{0} {1} endpoint is not in service catalog.')
                reason = reason.format(cls.default_client_name, service_type)
        return (False, reason)

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

    def heat(self):
        return self.client('heat')

    def glance(self):
        return self.client('glance')

    def _incr_atomic_key(self, last_key):
        if last_key is None:
            self._atomic_key = 1
        else:
            self._atomic_key = last_key + 1

    def _should_lock_on_action(self, action):
        """Return whether we should take a resource-level lock for an action.

        In the legacy path, we always took a lock at the Stack level and never
        at the Resource level. In convergence, we lock at the Resource level
        for most operations. However, there are currently some exceptions:
        the SUSPEND, RESUME, SNAPSHOT, and CHECK actions, and stack abandon.
        """
        return (self.stack.convergence and
                not self.abandon_in_progress and
                action in {self.ADOPT,
                           self.CREATE,
                           self.UPDATE,
                           self.ROLLBACK,
                           self.DELETE})

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
        attempts = 1
        first_iter = [True]  # work around no nonlocal in py27
        if self.stack.convergence:
            if self._should_lock_on_action(action):
                lock_acquire = self.LOCK_ACQUIRE
                lock_release = self.LOCK_RELEASE
            else:
                lock_acquire = lock_release = self.LOCK_RESPECT

            if action != self.CREATE:
                attempts += max(cfg.CONF.client_retry_limit, 0)
        else:
            lock_acquire = lock_release = self.LOCK_NONE

        # retry for convergence DELETE or UPDATE if we get the usual
        # lock-acquire exception of exception.UpdateInProgress
        @tenacity.retry(
            stop=tenacity.stop_after_attempt(attempts),
            retry=tenacity.retry_if_exception_type(
                exception.UpdateInProgress),
            wait=tenacity.wait_random(max=2),
            reraise=True)
        def set_in_progress():
            if not first_iter[0]:
                res_obj = resource_objects.Resource.get_obj(
                    self.context, self.id)
                self._atomic_key = res_obj.atomic_key
            else:
                first_iter[0] = False
            self.state_set(action, self.IN_PROGRESS, lock=lock_acquire)

        try:
            set_in_progress()
            yield
        except exception.UpdateInProgress as ex:
            with excutils.save_and_reraise_exception():
                LOG.info('Update in progress for %s', self.name)
        except expected_exceptions as ex:
            with excutils.save_and_reraise_exception():
                self.state_set(action, self.COMPLETE, six.text_type(ex),
                               lock=lock_release)
                LOG.debug('%s', six.text_type(ex))
        except Exception as ex:
            LOG.info('%(action)s: %(info)s',
                     {"action": action,
                      "info": six.text_type(self)},
                     exc_info=True)
            failure = exception.ResourceFailure(ex, self, action)
            self.state_set(action, self.FAILED, six.text_type(failure),
                           lock=lock_release)
            raise failure
        except BaseException as exc:
            with excutils.save_and_reraise_exception():
                try:
                    reason = six.text_type(exc)
                    msg = '%s aborted' % action
                    if reason:
                        msg += ' (%s)' % reason
                    self.state_set(action, self.FAILED, msg,
                                   lock=lock_release)
                except Exception:
                    LOG.exception('Error marking resource as failed')
        else:
            self.state_set(action, self.COMPLETE, lock=lock_release)

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
            try:
                handler_data = handler(*args)
            except StopIteration:
                raise RuntimeError('Plugin method raised StopIteration')
            yield
            if callable(check):
                try:
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
                except StopIteration:
                    raise RuntimeError('Plugin method raised StopIteration')
                except Exception:
                    raise
                except:  # noqa
                    with excutils.save_and_reraise_exception():
                        canceller = getattr(
                            self,
                            'handle_%s_cancel' % handler_action,
                            None
                        )
                        if callable(canceller):
                            try:
                                canceller(handler_data)
                            except Exception:
                                LOG.exception(
                                    'Error cancelling resource %s',
                                    action
                                )

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
        old_props = self._stored_properties_data
        self._stored_properties_data = function.resolve(self.properties.data)
        if self._stored_properties_data != old_props:
            self._rsrc_prop_data_id = None
            self.attributes.reset_resolved_values()

    def referenced_attrs(self, stk_defn=None,
                         in_resources=True, in_outputs=True,
                         load_all=False):
        """Return the set of all attributes referenced in the template.

        This enables the resource to calculate which of its attributes will
        be used. By default, attributes referenced in either other resources
        or outputs will be included. Either can be excluded by setting the
        `in_resources` or `in_outputs` parameters to False. To limit to a
        subset of outputs, pass an iterable of the output names to examine
        for the `in_outputs` parameter.

        The set of referenced attributes is calculated from the
        StackDefinition object provided, or from the stack's current
        definition if none is passed.
        """
        if stk_defn is None:
            stk_defn = self.stack.defn

        def get_dep_attrs(source):
            return set(itertools.chain.from_iterable(s.dep_attrs(self.name,
                                                                 load_all)
                                                     for s in source))

        refd_attrs = set()
        if in_resources:
            enabled_resources = stk_defn.enabled_rsrc_names()
            refd_attrs |= get_dep_attrs(stk_defn.resource_definition(r_name)
                                        for r_name in enabled_resources)

        subset_outputs = isinstance(in_outputs, collections.Iterable)
        if subset_outputs or in_outputs:
            if not subset_outputs:
                in_outputs = stk_defn.enabled_output_names()
            refd_attrs |= get_dep_attrs(stk_defn.output_definition(op_name)
                                        for op_name in in_outputs)

        if attributes.ALL_ATTRIBUTES in refd_attrs:
            refd_attrs.remove(attributes.ALL_ATTRIBUTES)
            refd_attrs |= (set(self.attributes) - {self.SHOW})

        return refd_attrs

    def node_data(self, stk_defn=None, for_resources=True, for_outputs=False):
        """Return a NodeData object representing the resource.

        The NodeData object returned contains basic data about the resource,
        including its name, ID and state, as well as its reference ID and any
        attribute values that are used.

        By default, those attribute values that are referenced by other
        resources are included. These can be ignored by setting the
        for_resources parameter to False. If the for_outputs parameter is
        True, those attribute values that are referenced by stack outputs are
        included. If the for_outputs parameter is an iterable of output names,
        only those attribute values referenced by the specified stack outputs
        are included.

        The set of referenced attributes is calculated from the
        StackDefinition object provided, or from the stack's current
        definition if none is passed.

        After calling this method, the resource's attribute cache is
        populated with any cacheable attribute values referenced by stack
        outputs, even if they are not also referenced by other resources.
        """
        def get_attrs(attrs, cacheable_only=False):
            for attr in attrs:
                path = (attr,) if isinstance(attr, six.string_types) else attr
                if (cacheable_only and
                    (self.attributes.get_cache_mode(path[0]) ==
                     attributes.Schema.CACHE_NONE)):
                    continue
                if self.action == self.INIT:
                    if (path[0] in self.attributes or
                        (type(self).get_attribute != Resource.get_attribute or
                         type(self).FnGetAtt != Resource.FnGetAtt)):
                        # TODO(ricolin) make better placeholder values here
                        yield attr, None
                else:
                    try:
                        yield attr, self.FnGetAtt(*path)
                    except exception.InvalidTemplateAttribute as ita:
                        # Attribute doesn't exist, so don't store it. Whatever
                        # tries to access it will get another
                        # InvalidTemplateAttribute exception at that point
                        LOG.info('%s', ita)
                    except Exception as exc:
                        # Store the exception that occurred. It will be
                        # re-raised when something tries to access it, or when
                        # we try to serialise the NodeData.
                        yield attr, exc

        load_all = not self.stack.in_convergence_check
        dep_attrs = self.referenced_attrs(stk_defn,
                                          in_resources=for_resources,
                                          in_outputs=for_outputs,
                                          load_all=load_all)

        # Ensure all attributes referenced in outputs get cached
        if for_outputs is False and self.stack.convergence:
            out_attrs = self.referenced_attrs(stk_defn, in_resources=False,
                                              load_all=load_all)
            for e in get_attrs(out_attrs - dep_attrs, cacheable_only=True):
                pass

        # Calculate attribute values *before* reference ID, to potentially
        # save an extra RPC call in TemplateResource
        attribute_values = dict(get_attrs(dep_attrs))

        return node_data.NodeData(self.id, self.name, self.uuid,
                                  self.FnGetRefId(), attribute_values,
                                  self.action, self.status)

    def preview(self):
        """Default implementation of Resource.preview.

        This method should be overridden by child classes for specific
        behavior.
        """
        return self

    def create_convergence(self, template_id, requires, engine_id,
                           timeout, progress_callback=None):
        """Creates the resource by invoking the scheduler TaskRunner."""
        self._calling_engine_id = engine_id
        self.requires = requires
        self.current_template_id = template_id
        if self.stack.adopt_stack_data is None:
            runner = scheduler.TaskRunner(self.create)
        else:
            adopt_data = self.stack._adopt_kwargs(self)
            runner = scheduler.TaskRunner(self.adopt, **adopt_data)

        runner(timeout=timeout, progress_callback=progress_callback)

    def validate_external(self):
        if self.external_id is not None:
            try:
                self.resource_id = self.external_id
                self._show_resource()
            except Exception as ex:
                if self._default_client_plugin().is_not_found(ex):
                    error_message = (_("Invalid external resource: Resource "
                                       "%(external_id)s (%(type)s) can not "
                                       "be found.") %
                                     {'external_id': self.external_id,
                                      'type': self.type()})
                    raise exception.StackValidationFailed(
                        message="%s" % error_message)
                raise

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

        if self.external_id is not None:
            yield self._do_action(self.ADOPT,
                                  resource_data={
                                      'resource_id': self.external_id})
            self.check()
            return

        # This method can be called when we replace a resource, too. In that
        # case, a hook has already been dealt with in `Resource.update` so we
        # shouldn't do it here again:
        if self.stack.action == self.stack.CREATE:
            yield self._break_if_required(
                self.CREATE, environment.HOOK_PRE_CREATE)

        LOG.info('creating %s', self)

        # Re-resolve the template, since if the resource Ref's
        # the StackId pseudo parameter, it will change after
        # the parser.Stack is stored (which is after the resources
        # are __init__'d, but before they are create()'d). We also
        # do client lookups for RESOLVE translation rules here.

        self.reparse()
        self._update_stored_properties()

        count = {self.CREATE: 0, self.DELETE: 0}

        retry_limit = max(cfg.CONF.action_retry_limit, 0)
        first_failure = None

        while (count[self.CREATE] <= retry_limit and
               count[self.DELETE] <= retry_limit):
            pre_func = None
            if count[action] > 0:
                delay = timeutils.retry_backoff_delay(count[action],
                                                      jitter_max=2.0)
                waiter = scheduler.TaskRunner(self.pause)
                yield waiter.as_task(timeout=delay)
            elif action == self.CREATE:
                # Only validate properties in first create call.
                pre_func = self.properties.validate

            try:
                yield self._do_action(action, pre_func)
                if action == self.CREATE:
                    first_failure = None
                    break
                else:
                    action = self.CREATE
            except exception.ResourceFailure as failure:
                exc = failure.exc
                if isinstance(exc, exception.StackValidationFailed):
                    path = [self.t.name]
                    path.extend(exc.path)
                    raise exception.ResourceFailure(
                        exception_or_error=exception.StackValidationFailed(
                            error=exc.error,
                            path=path,
                            message=exc.error_message
                        ),
                        resource=failure.resource,
                        action=failure.action
                    )
                if not (isinstance(exc, exception.ResourceInError) or
                        self._default_client_plugin().is_conflict(exc)):
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

    @staticmethod
    def pause():
        try:
            while True:
                yield
        except scheduler.Timeout:
            return

    def prepare_abandon(self):
        self.abandon_in_progress = True
        return {
            'name': self.name,
            'resource_id': self.resource_id,
            'type': self.type(),
            'action': self.action,
            'status': self.status,
            'metadata': self.metadata_get(),
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
        return []

    def translate_properties(self, properties,
                             client_resolve=True, ignore_resolve_error=False):
        """Set resource specific rules for properties translation.

        The properties parameter is a properties object and the
        optional client_resolve flag is to specify whether to
        do 'RESOLVE' translation with client lookup.
        """
        rules = self.translation_rules(properties) or []
        properties.update_translation(
            rules, client_resolve=client_resolve,
            ignore_resolve_error=ignore_resolve_error)

    def cancel_grace_period(self):
        canceller = getattr(self,
                            'handle_%s_cancel' % self.action.lower(),
                            None)
        if callable(canceller):
            return None

        return cfg.CONF.error_wait_time

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

    def needs_replace_failed(self):
        """Needs replace if resource is in ``*_FAILED``."""
        return True

    def _needs_update(self, after, before, after_props, before_props,
                      prev_resource, check_init_complete=True):
        if self.status == self.FAILED:
            # always replace when a resource is in CHECK_FAILED
            if self.action == self.CHECK or self.needs_replace_failed():
                raise UpdateReplace(self)

        if self.state == (self.DELETE, self.COMPLETE):
            raise UpdateReplace(self)

        if (check_init_complete and
                self.state == (self.INIT, self.COMPLETE)):
            raise UpdateReplace(self)

        if self.needs_replace(after_props):
            raise UpdateReplace(self)

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
            raise UpdateReplace(self.name)

    def update_convergence(self, template_id, new_requires, engine_id,
                           timeout, new_stack, progress_callback=None):
        """Update the resource synchronously.

        Persist the resource's current_template_id to template_id and
        resource's requires to list of the required resource ids from the given
        resource_data and existing resource's requires, then updates the
        resource by invoking the scheduler TaskRunner.
        """
        self._calling_engine_id = engine_id

        # Check that the resource type matches. If the type has changed by a
        # legitimate substitution, the load()ed resource will already be of
        # the new type.
        registry = new_stack.env.registry
        new_res_def = new_stack.defn.resource_definition(self.name)
        new_res_type = registry.get_class_to_instantiate(
            new_res_def.resource_type, resource_name=self.name)
        if type(self) is not new_res_type:
            restrictions = registry.get_rsrc_restricted_actions(self.name)
            self._check_for_convergence_replace(restrictions)

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
        self.replaced_by = None

        runner = scheduler.TaskRunner(self.update, new_res_def,
                                      new_template_id=template_id,
                                      new_requires=new_requires)
        runner(timeout=timeout, progress_callback=progress_callback)

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
                raise UpdateReplace(self)

            self.update_template_diff_properties(after_props, before_props)
            return True
        else:
            return False

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
        except UpdateReplace:
            if 'replace' in actions:
                raise exception.ResourceActionRestricted(action='replace')
            raise

        return False

    def _prepare_update_props(self, after, before):

        before_props = before.properties(self.properties_schema,
                                         self.context)

        # Regenerate the schema, else validation would fail
        self.regenerate_info_schema(after)
        after.set_translation_rules(self.translation_rules(self.properties))
        after_props = after.properties(self.properties_schema,
                                       self.context)
        self.translate_properties(after_props)
        self.translate_properties(before_props, ignore_resolve_error=True)

        if (cfg.CONF.observe_on_update or self.converge) and before_props:
            if not self.resource_id:
                raise UpdateReplace(self)

            try:
                resource_reality = self.get_live_state(before_props)
                if resource_reality:
                    self._update_properties_with_live_state(before_props,
                                                            resource_reality)
            except exception.EntityNotFound:
                raise UpdateReplace(self)
            except Exception as ex:
                LOG.warning("Resource cannot be updated with it's "
                            "live state in case of next "
                            "error: %s", ex)
        return after_props, before_props

    def _prepare_update_replace_handler(self, action):
        """Return the handler method for preparing to replace a resource.

        This may be either restore_prev_rsrc() (in the case of a legacy
        rollback) or, more typically, prepare_for_replace().

        If the plugin has not overridden the method, then None is returned in
        place of the default method (which is empty anyway).
        """
        if (self.stack.action == 'ROLLBACK' and
                self.stack.status == 'IN_PROGRESS' and
                not self.stack.convergence):
            # handle case, when it's rollback and we should restore
            # old resource
            if self.restore_prev_rsrc != Resource.restore_prev_rsrc:
                return self.restore_prev_rsrc
        else:
            if self.prepare_for_replace != Resource.prepare_for_replace:
                return self.prepare_for_replace
        return None

    def _prepare_update_replace(self, action):
        handler = self._prepare_update_replace_handler(action)
        if handler is None:
            return

        try:
            handler()
        except Exception as e:
            # if any exception happen, we should set the resource to
            # FAILED, then raise ResourceFailure
            failure = exception.ResourceFailure(e, self, action)
            self.state_set(action, self.FAILED, six.text_type(failure))
            raise failure

    @classmethod
    def check_is_substituted(cls, new_res_type):
            support_status = getattr(cls, 'support_status', None)
            if support_status:
                is_substituted = support_status.is_substituted(new_res_type)
                return is_substituted
            return False

    def _persist_update_no_change(self, new_template_id):
        """Persist an update where the resource is unchanged."""
        if new_template_id is not None:
            self.current_template_id = new_template_id
        lock = (self.LOCK_RESPECT if self.stack.convergence
                else self.LOCK_NONE)
        if self.status == self.FAILED:
            status_reason = _('Update status to COMPLETE for '
                              'FAILED resource neither update '
                              'nor replace.')
            self.state_set(self.action, self.COMPLETE,
                           status_reason, lock=lock)
        elif new_template_id is not None:
            self.store(lock=lock)

    @scheduler.wrappertask
    def update(self, after, before=None, prev_resource=None,
               new_template_id=None, new_requires=None):
        """Return a task to update the resource.

        Subclasses should provide a handle_update() method to customise update,
        the base-class handle_update will fail by default.
        """
        action = self.UPDATE

        assert isinstance(after, rsrc_defn.ResourceDefinition)
        if before is None:
            before = self.frozen_definition()

        after_external_id = after.external_id()
        if self.external_id != after_external_id:
            msg = _("Update to property %(prop)s of %(name)s (%(res)s)"
                    ) % {'prop': hot_tmpl.HOTemplate20161014.RES_EXTERNAL_ID,
                         'res': self.type(), 'name': self.name}
            exc = exception.NotSupported(feature=msg)
            raise exception.ResourceFailure(exc, self, action)
        elif after_external_id is not None:
            LOG.debug("Skip update on external resource.")
            self._persist_update_no_change(new_template_id)
            return

        after_props, before_props = self._prepare_update_props(after, before)

        yield self._break_if_required(
            self.UPDATE, environment.HOOK_PRE_UPDATE)

        try:
            registry = self.stack.env.registry
            restr_actions = registry.get_rsrc_restricted_actions(self.name)
            if restr_actions:
                needs_update = self._check_restricted_actions(restr_actions,
                                                              after, before,
                                                              after_props,
                                                              before_props,
                                                              prev_resource)
            else:
                needs_update = self._needs_update(after, before,
                                                  after_props, before_props,
                                                  prev_resource)
        except UpdateReplace:
            with excutils.save_and_reraise_exception():
                if self._prepare_update_replace_handler(action) is not None:
                    with self.lock(self._calling_engine_id):
                        self._prepare_update_replace(action)
        except exception.ResourceActionRestricted as ae:
            failure = exception.ResourceFailure(ae, self, action)
            self._add_event(action, self.FAILED, six.text_type(ae))
            raise failure

        if not needs_update:
            self._persist_update_no_change(new_template_id)
            return

        if not self.stack.convergence:
            if (self.action, self.status) in (
                    (self.CREATE, self.IN_PROGRESS),
                    (self.UPDATE, self.IN_PROGRESS),
                    (self.ADOPT, self.IN_PROGRESS)):
                exc = Exception(_('Resource update already requested'))
                raise exception.ResourceFailure(exc, self, action)

        LOG.info('updating %s', self)

        self.updated_time = datetime.utcnow()

        if new_requires is not None:
            self.requires = self.requires | new_requires

        with self._action_recorder(action, UpdateReplace):
            after_props.validate()
            self.properties = before_props
            tmpl_diff = self.update_template_diff(after.freeze(), before)
            self.old_template_id = self.current_template_id

            try:
                if tmpl_diff and self.needs_replace_with_tmpl_diff(tmpl_diff):
                    raise UpdateReplace(self)

                prop_diff = self.update_template_diff_properties(after_props,
                                                                 before_props)

                if new_template_id is not None:
                    self.current_template_id = new_template_id

                yield self.action_handler_task(action,
                                               args=[after, tmpl_diff,
                                                     prop_diff])
            except UpdateReplace:
                with excutils.save_and_reraise_exception():
                    self.current_template_id = self.old_template_id
                    self.old_template_id = None
                    self._prepare_update_replace(action)

            self.t = after
            self.reparse()
            self._update_stored_properties()
            if new_requires is not None:
                self.requires = new_requires

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
        database accordingly. If check is not supported by the resource,
        default action is to fail and revert the resource's status to its
        original state with the added message that check was not performed.
        """
        action = self.CHECK
        LOG.info('Checking %s', self)

        if hasattr(self, 'handle_%s' % action.lower()):
            if self.state == (self.INIT, self.COMPLETE):
                reason = _('Can not check %s, resource not '
                           'created yet.') % self.name
                self.state_set(action, self.FAILED, reason)
                exc = Exception(_('Resource %s not created yet.') % self.name)
                failure = exception.ResourceFailure(exc, self, action)
                raise failure

            with self.frozen_properties():
                return self._do_action(action)
        else:
            if self.state == (self.INIT, self.COMPLETE):
                # No need to store status; better to leave the resource in
                # INIT_COMPLETE than imply that we've checked and it exists.
                return
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

        LOG.info('suspending %s', self)
        with self.frozen_properties():
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

        LOG.info('resuming %s', self)
        with self.frozen_properties():
            return self._do_action(action)

    def snapshot(self):
        """Snapshot the resource and return the created data, if any."""
        LOG.info('snapshotting %s', self)
        with self.frozen_properties():
            return self._do_action(self.SNAPSHOT)

    @scheduler.wrappertask
    def delete_snapshot(self, data):
        yield self.action_handler_task('delete_snapshot', args=[data])

    def physical_resource_name(self):
        if self.id is None or self.action == self.INIT:
            return None

        name = '%s-%s-%s' % (self.stack.name.rstrip('*'),
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
        LOG.info('Validating %s', self)
        return self.validate_template()

    def validate_template(self):
        """Validate structural/syntax aspects of the resource definition.

        Resource plugins should not override this, because this interface
        is expected to be called pre-create so things normally valid
        in an overridden validate() such as accessing properties
        may not work.
        """
        self._validate_service_availability(
            self.stack.context,
            self.t.resource_type
        )
        try:
            self.t.validate()
            self.validate_deletion_policy(self.t.deletion_policy())
            self.t.update_policy(self.update_policy_schema,
                                 self.context).validate()
            validate = self.properties.validate(
                with_value=self.stack.strict_validate)
        except exception.StackValidationFailed as ex:
            path = [self.stack.t.RESOURCES, self.t.name]
            if ex.path:
                path.append(self.stack.t.get_section_name(ex.path[0]))
                path.extend(ex.path[1:])
            raise exception.StackValidationFailed(
                error=ex.error,
                path=path,
                message=ex.error_message)
        return validate

    @classmethod
    def validate_deletion_policy(cls, policy):
        path = rsrc_defn.DELETION_POLICY
        if policy not in rsrc_defn.ResourceDefinition.DELETION_POLICIES:
            msg = _('Invalid deletion policy "%s"') % policy
            raise exception.StackValidationFailed(message=msg, path=path)

        if policy == rsrc_defn.ResourceDefinition.SNAPSHOT:
            if not callable(getattr(cls, 'handle_snapshot_delete', None)):
                msg = _('"%s" deletion policy not supported') % policy
                raise exception.StackValidationFailed(message=msg, path=path)

    def _update_replacement_data(self, template_id):
        # Update the replacement resource's replaces field.
        # Make sure that the replacement belongs to the given
        # template and there is no engine working on it.
        if self.replaced_by is None:
            return

        try:
            db_res = resource_objects.Resource.get_obj(
                self.context, self.replaced_by,
                fields=('current_template_id', 'atomic_key'))
        except exception.NotFound:
            LOG.info("Could not find replacement of resource %(name)s "
                     "with id %(id)s while updating replaces.",
                     {'name': self.name, 'id': self.replaced_by})
            return

        if (db_res.current_template_id == template_id):
            # Following update failure is ignorable; another
            # update might have locked/updated the resource.
            db_res.select_and_update({'replaces': None},
                                     atomic_key=db_res.atomic_key,
                                     expected_engine_id=None)

    def delete_convergence(self, template_id, engine_id, timeout,
                           progress_callback=None):
        """Destroys the resource if it doesn't belong to given template.

        The given template is suppose to be the current template being
        provisioned.

        Also, since this resource is visited as part of clean-up phase,
        the needed_by should be updated. If this resource was
        replaced by more recent resource, then delete this and update
        the replacement resource's replaces field.
        """
        self._calling_engine_id = engine_id

        if self.current_template_id != template_id:
            # just delete the resources in INIT state
            if self.action == self.INIT:
                try:
                    resource_objects.Resource.delete(self.context, self.id)
                except exception.NotFound:
                    pass
            else:
                runner = scheduler.TaskRunner(self.delete)
                runner(timeout=timeout,
                       progress_callback=progress_callback)
                self._update_replacement_data(template_id)

    def handle_delete(self):
        """Default implementation; should be overridden by resources."""
        if self.entity and self.resource_id is not None:
            with self._default_client_plugin().ignore_not_found:
                obj = getattr(self.client(), self.entity)
                obj.delete(self.resource_id)
                return self.resource_id
        return None

    @scheduler.wrappertask
    def delete(self):
        """A task to delete the resource.

        Subclasses should provide a handle_delete() method to customise
        deletion.
        """
        @excutils.exception_filter
        def should_retry(exc):
            if count >= retry_limit:
                return False
            return (self._default_client_plugin().is_conflict(exc) or
                    isinstance(exc, exception.PhysicalResourceExists))

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

        LOG.info('deleting %s', self)

        if self._stored_properties_data is not None:
            # On delete we can't rely on re-resolving the properties
            # so use the stored frozen_definition instead
            self.properties = self.frozen_definition().properties(
                self.properties_schema, self.context)
            self.translate_properties(self.properties,
                                      ignore_resolve_error=True)

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

                count = -1
                retry_limit = max(cfg.CONF.action_retry_limit, 0)

                while True:
                    count += 1
                    LOG.info('delete %(name)s attempt %(attempt)d' %
                             {'name': six.text_type(self), 'attempt': count+1})
                    if count:
                        delay = timeutils.retry_backoff_delay(count,
                                                              jitter_max=2.0)
                        waiter = scheduler.TaskRunner(self.pause)
                        yield waiter.as_task(timeout=delay)
                    with excutils.exception_filter(should_retry):
                        yield self.action_handler_task(action,
                                                       *action_args)
                        break

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
                LOG.warning('db error %s', ex)

    def store(self, set_metadata=False, lock=LOCK_NONE):
        """Create the resource in the database.

        If self.id is set, we update the existing stack.
        """
        if not self.root_stack_id:
            self.root_stack_id = self.stack.root_stack_id()

        rs = {'action': self.action,
              'status': self.status,
              'status_reason': six.text_type(self.status_reason),
              'stack_id': self.stack.id,
              'physical_resource_id': self.resource_id,
              'name': self.name,
              'rsrc_prop_data_id':
                  self._create_or_replace_rsrc_prop_data(),
              'needed_by': [],
              'requires': sorted(self.requires, reverse=True),
              'replaces': self.replaces,
              'replaced_by': self.replaced_by,
              'current_template_id': self.current_template_id,
              'root_stack_id': self.root_stack_id,
              'updated_at': self.updated_time,
              'properties_data': None}

        if set_metadata:
            metadata = self.t.metadata()
            rs['rsrc_metadata'] = metadata
            self._rsrc_metadata = metadata

        if self.id is not None:
            if (lock == self.LOCK_NONE or
                (lock in {self.LOCK_ACQUIRE, self.LOCK_RELEASE} and
                 self._calling_engine_id is None)):
                resource_objects.Resource.update_by_id(
                    self.context, self.id, rs)
                if lock != self.LOCK_NONE:
                    LOG.error('No calling_engine_id in store() %s',
                              six.text_type(rs))
            else:
                self._store_with_lock(rs, lock)
        else:
            new_rs = resource_objects.Resource.create(self.context, rs)
            self.id = new_rs.id
            self.uuid = new_rs.uuid
            self.created_time = new_rs.created_at

    def _store_with_lock(self, rs, lock):
        if lock == self.LOCK_ACQUIRE:
            rs['engine_id'] = self._calling_engine_id
            expected_engine_id = None
        elif lock == self.LOCK_RESPECT:
            expected_engine_id = None
        elif lock == self.LOCK_RELEASE:
            expected_engine_id = self._calling_engine_id
            rs['engine_id'] = None
        else:
            assert False, "Invalid lock action: %s" % lock
        if resource_objects.Resource.select_and_update_by_id(
                self.context, self.id, rs, expected_engine_id,
                self._atomic_key):
            self._incr_atomic_key(self._atomic_key)
        else:
            LOG.info('Resource %s is locked or does not exist',
                     six.text_type(self))
            LOG.debug('Resource id:%(resource_id)s locked or does not exist. '
                      'Expected atomic_key:%(atomic_key)s, '
                      'accessing from engine_id:%(engine_id)s',
                      {'resource_id': self.id,
                       'atomic_key': self._atomic_key,
                       'engine_id': self._calling_engine_id})
            raise exception.UpdateInProgress(self.name)

    def _add_event(self, action, status, reason):
        """Add a state change event to the database."""
        physical_res_id = self.resource_id or self.physical_resource_name()
        ev = event.Event(self.context, self.stack, action, status, reason,
                         physical_res_id, self._rsrc_prop_data_id,
                         self._stored_properties_data, self.name, self.type())

        ev.store()
        self.stack.dispatch_event(ev)

    @contextlib.contextmanager
    def lock(self, engine_id):
        self._calling_engine_id = engine_id
        try:
            if engine_id is not None:
                self._store_with_lock({}, self.LOCK_ACQUIRE)
            yield
        except exception.UpdateInProgress:
            raise
        except BaseException:
            with excutils.save_and_reraise_exception():
                if engine_id is not None:
                    self._store_with_lock({}, self.LOCK_RELEASE)
        else:
            if engine_id is not None:
                self._store_with_lock({}, self.LOCK_RELEASE)

    def _resolve_any_attribute(self, attr):
        """Method for resolving any attribute, including base attributes.

        This method uses basic _resolve_attribute method for resolving
        plugin-specific attributes. Base attributes will be resolved with
        corresponding method, which should be defined in each resource
        class.

        :param attr: attribute name, which will be resolved
        :returns: method of resource class, which resolve base attribute
        """
        if attr in self.base_attributes_schema:
            # check resource_id, because usually it is required for getting
            # information about resource
            if self.resource_id is not None:
                with self._default_client_plugin().ignore_not_found:
                    return getattr(self, '_{0}_resource'.format(attr))()
        else:
            with self._default_client_plugin().ignore_not_found:
                return self._resolve_attribute(attr)
        return None

    def _show_resource(self):
        """Default implementation; should be overridden by resources.

        :returns: the map of resource information or None
        """
        if self.entity and self.default_client_name is not None:
            try:
                obj = getattr(self.client(), self.entity)
                resource = obj.get(self.resource_id)
                if isinstance(resource, dict):
                    return resource
                else:
                    return resource.to_dict()
            except AttributeError as ex:
                LOG.warning("Resolving 'show' attribute has failed : %s",
                            ex)
                return None

    def get_live_resource_data(self):
        """Default implementation; can be overridden by resources.

        Get resource data and handle it with exceptions.
        """
        try:
            resource_data = self._show_resource()
        except Exception as ex:
            if self._default_client_plugin().is_not_found(ex):
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
        resource_result = {}
        for key in self._update_allowed_properties:
            if key in resource_data:
                if key == 'name' and resource_properties.get(key) is None:
                    # We use `physical_resource_name` for name property in some
                    # resources when name not provided during create, so we
                    # shouldn't add name in resource_data if it's None in
                    # property (might just the cases that we using
                    # `physical_resource_name`).
                    continue
                resource_result[key] = resource_data.get(key)

        return resource_result

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

    def state_set(self, action, status, reason="state changed",
                  lock=LOCK_NONE):
        if action not in self.ACTIONS:
            raise ValueError(_("Invalid action %s") % action)

        if status not in self.STATUSES:
            raise ValueError(_("Invalid status %s") % status)

        old_state = (self.action, self.status)
        new_state = (action, status)
        set_metadata = self.action == self.INIT
        self.action = action
        self.status = status
        self.status_reason = reason
        self.store(set_metadata, lock=lock)

        if new_state != old_state:
            self._add_event(action, status, reason)

        if status != self.COMPLETE:
            self.clear_stored_attributes()

    @property
    def state(self):
        """Returns state, tuple of action, status."""
        return (self.action, self.status)

    def store_attributes(self):
        assert self.id is not None
        if self.status != self.COMPLETE or self.action in (self.INIT,
                                                           self.DELETE):
            return
        if not self.attributes.has_new_cached_attrs():
            return

        try:
            attr_data_id = resource_objects.Resource.store_attributes(
                self.context, self.id, self._atomic_key,
                self.attributes.cached_attrs, self._attr_data_id)
            if attr_data_id is not None:
                self._incr_atomic_key(self._atomic_key)
                self._attr_data_id = attr_data_id
        except Exception as ex:
            LOG.error('store_attributes rsrc %(name)s %(id)s DB error %(ex)s',
                      {'name': self.name, 'id': self.id, 'ex': ex})

    def clear_stored_attributes(self):
        if self._attr_data_id:
            resource_objects.Resource.attr_data_delete(
                self.context, self.id, self._attr_data_id)
        self.attributes.reset_resolved_values()

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
        cache_custom = ((self.attributes.get_cache_mode(key) !=
                         attributes.Schema.CACHE_NONE) and
                        (type(self).get_attribute != Resource.get_attribute))
        if cache_custom:
            if path:
                full_key = sync_point.str_pack_tuple((key,) + path)
            else:
                full_key = key
            if full_key in self.attributes.cached_attrs:
                return self.attributes.cached_attrs[full_key]

        attr_val = self.get_attribute(key, *path)

        if cache_custom:
            self.attributes.set_cached_attr(full_key, attr_val)
        return attr_val

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
        LOG.info('Clearing %(hook)s hook on %(resource)s',
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

            return 'Unknown'

        try:
            signal_result = self.handle_signal(details)
            if signal_result:
                reason_string = "Signal: %s" % signal_result
            else:
                reason_string = get_string_details()
            self._add_event('SIGNAL', self.status, reason_string)
        except NoActionRequired:
            # Don't log an event as it just spams the user.
            pass
        except Exception as ex:
            if hasattr(self, '_db_res_is_deleted'):
                # No spam required
                return
            LOG.info('signal %(name)s : %(msg)s',
                     {'name': six.text_type(self),
                      'msg': six.text_type(ex)},
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
            self._signal_check_hook(details)
        if details and 'unset_hook' in details:
            self._unset_hook(details)
            return False
        if need_check:
            self._signal_check_action()

        with self.frozen_properties():
            self._handle_signal(details)

        return self.signal_needs_metadata_updates

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            raise UpdateReplace(self.name)

    def metadata_update(self, new_metadata=None):
        """No-op for resources which don't explicitly override this method."""
        if new_metadata:
            LOG.warning("Resource %s does not implement metadata update",
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

        props_schema = {}
        for name, schema_dict in cls.properties_schema.items():
            schema = properties.Schema.from_legacy(schema_dict)
            if schema.support_status.status != support.HIDDEN:
                props_schema[name] = schema

        params, props = (properties.Properties.
                         schema_to_parameters_and_properties(props_schema,
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
                hot_tmpl.HOTemplate20161014.VERSION: '2016-10-14',
                hot_tmpl.HOTemplate20161014.DESCRIPTION: description,
                hot_tmpl.HOTemplate20161014.PARAMETERS: params,
                hot_tmpl.HOTemplate20161014.OUTPUTS: outputs,
                hot_tmpl.HOTemplate20161014.RESOURCES: {
                    res_name: {
                        hot_tmpl.HOTemplate20161014.RES_TYPE: res_type,
                        hot_tmpl.HOTemplate20161014.RES_PROPERTIES: props}}}
        else:
            tmpl_dict = {
                cfn_tmpl.CfnTemplate.ALTERNATE_VERSION: '2012-12-12',
                cfn_tmpl.CfnTemplate.DESCRIPTION: description,
                cfn_tmpl.CfnTemplate.PARAMETERS: params,
                cfn_tmpl.CfnTemplate.RESOURCES: {
                    res_name: {
                        cfn_tmpl.CfnTemplate.RES_TYPE: res_type,
                        cfn_tmpl.CfnTemplate.RES_PROPERTIES: props}
                },
                cfn_tmpl.CfnTemplate.OUTPUTS: outputs}

        return tmpl_dict

    def data(self):
        """Return the resource data for this resource.

        Use methods data_set and data_delete to modify the resource data
        for this resource.

        :returns: a dict representing the resource data for this resource.
        """
        if self._data is None and self.id is not None:
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

    def _create_or_replace_rsrc_prop_data(self):
        if self._rsrc_prop_data_id is not None:
            return self._rsrc_prop_data_id

        if not self._stored_properties_data:
            return None

        self._rsrc_prop_data_id = \
            rpd_objects.ResourcePropertiesData(self.context).create(
                self.context, self._stored_properties_data).id
        return self._rsrc_prop_data_id

    def is_using_neutron(self):
        try:
            sess_client = self.client('neutron').httpclient
            if not sess_client.get_endpoint():
                return False
        except Exception:
            return False
        return True

    @staticmethod
    def _make_resolver(ref):
        """Return an attribute resolution method.

        This builds a resolver without a strong reference to this resource, to
        break a possible cycle.
        """
        def resolve(attr):
            res = ref()
            if res is None:
                raise RuntimeError("Resource collected")
            return res._resolve_any_attribute(attr)
        return resolve
