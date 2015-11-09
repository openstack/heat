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
from oslo_utils import encodeutils
from oslo_utils import excutils
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
from heat.engine import environment
from heat.engine import event
from heat.engine import function
from heat.engine import properties
from heat.engine import resources
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import support
from heat.objects import resource as resource_objects
from heat.objects import resource_data as resource_data_objects
from heat.rpc import client as rpc_client

cfg.CONF.import_opt('action_retry_limit', 'heat.common.config')

LOG = logging.getLogger(__name__)

datetime = dt.datetime


def _register_class(resource_type, resource_class):
    resources.global_env().register_class(resource_type, resource_class)


class UpdateReplace(Exception):
    '''Raised when resource update requires replacement.'''
    def __init__(self, resource_name='Unknown'):
        msg = _("The Resource %s requires replacement.") % resource_name
        super(Exception, self).__init__(six.text_type(msg))


class NoActionRequired(Exception):
    pass


class ResourceInError(exception.HeatException):
    msg_fmt = _('Went to status %(resource_status)s '
                'due to "%(status_reason)s"')

    def __init__(self, status_reason=_('Unknown'), **kwargs):
        super(ResourceInError, self).__init__(status_reason=status_reason,
                                              **kwargs)


class ResourceUnknownStatus(exception.HeatException):
    msg_fmt = _('%(result)s - Unknown status %(resource_status)s due to '
                '"%(status_reason)s"')

    def __init__(self, result=_('Resource failed'),
                 status_reason=_('Unknown'), **kwargs):
        super(ResourceUnknownStatus, self).__init__(
            result=result, status_reason=status_reason, **kwargs)


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

    # If True, this resource must be created before it can be referenced.
    strict_dependency = True

    # Resource implementation set this to the subset of resource properties
    # supported for handle_update, used by update_template_diff_properties
    update_allowed_properties = ()

    # Resource implementations set this to the name: description dictionary
    # that describes the appropriate resource attributes
    attributes_schema = {}

    # If True, this resource may perform authenticated API requests
    # throughout its lifecycle
    requires_deferred_auth = False

    # Limit to apply to physical_resource_name() size reduction algorithm.
    # If set to None no limit will be applied.
    physical_resource_name_limit = 255

    support_status = support.SupportStatus()

    # Default name to use for calls to self.client()
    default_client_name = None

    # no signal actions
    no_signal_actions = (SUSPEND, DELETE)

    # Whether all other resources need a metadata_update() after
    # a signal to this resource
    signal_needs_metadata_updates = True

    def __new__(cls, name, definition, stack):
        '''Create a new Resource of the appropriate class for its type.'''

        assert isinstance(definition, rsrc_defn.ResourceDefinition)

        if cls != Resource:
            # Call is already for a subclass, so pass it through
            ResourceClass = cls
        else:
            from heat.engine.resources import template_resource

            registry = stack.env.registry
            try:
                ResourceClass = registry.get_class(definition.resource_type,
                                                   resource_name=name)
            except exception.TemplateNotFound:
                ResourceClass = template_resource.TemplateResource
            assert issubclass(ResourceClass, Resource)

        return super(Resource, cls).__new__(ResourceClass)

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
        self.reparse()
        self.attributes = attributes.Attributes(self.name,
                                                self.attributes_schema,
                                                self._resolve_attribute)

        self.abandon_in_progress = False

        self.resource_id = None
        # if the stack is being deleted, assume we've already been deleted
        if stack.action == stack.DELETE:
            self.action = self.DELETE
        else:
            self.action = self.INIT
        self.status = self.COMPLETE
        self.status_reason = ''
        self.id = None
        self.uuid = None
        self._data = {}
        self._rsrc_metadata = None
        self._stored_properties_data = None
        self.created_time = None
        self.updated_time = None
        self._rpc_client = None
        self.needed_by = None
        self.requires = None
        self.replaces = None
        self.replaced_by = None
        self.current_template_id = stack.t.id

        resource = stack.db_resource_get(name)
        if resource:
            self._load_data(resource)

    def rpc_client(self):
        '''Return a client for making engine RPC calls.'''
        if not self._rpc_client:
            self._rpc_client = rpc_client.EngineClient()
        return self._rpc_client

    def _load_data(self, resource):
        '''Load the resource state from its DB representation.'''
        self.resource_id = resource.nova_instance
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

    @property
    def stack(self):
        stack = self._stackref()
        assert stack is not None, "Need a reference to the Stack object"
        return stack

    @stack.setter
    def stack(self, stack):
        self._stackref = weakref.ref(stack)

    def reparse(self):
        self.properties = self.t.properties(self.properties_schema,
                                            self.context)

    def __eq__(self, other):
        '''Allow == comparison of two resources.'''
        # For the purposes of comparison, we declare two resource objects
        # equal if their names and parsed_templates are the same
        if isinstance(other, Resource):
            return (self.name == other.name) and (
                self.parsed_template() == other.parsed_template())
        return NotImplemented

    def __ne__(self, other):
        '''Allow != comparison of two resources.'''
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    @property
    def metadata(self):
        """DEPRECATED. use method metadata_get instead."""
        warnings.warn('metadata attribute is deprecated, '
                      'use method metadata_get instead',
                      DeprecationWarning)
        return self.metadata_get(True)

    @metadata.setter
    def metadata(self, metadata):
        """DEPRECATED. use method metadata_set instead."""
        warnings.warn('metadata attribute is deprecated, '
                      'use method metadata_set instead',
                      DeprecationWarning)
        self.metadata_set(metadata)

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

    def metadata_set(self, metadata):
        if self.id is None or self.action == self.INIT:
            raise exception.ResourceNotAvailable(resource_name=self.name)
        rs = resource_objects.Resource.get_obj(self.stack.context, self.id)
        rs.update_and_save({'rsrc_metadata': metadata})
        self._rsrc_metadata = metadata

    def _break_if_required(self, action, hook):
        '''Block the resource until the hook is cleared if there is one.'''
        if self.stack.env.registry.matches_hook(self.name, hook):
            self._add_event(self.action, self.status,
                            _("%(a)s paused until Hook %(h)s is cleared")
                            % {'a': action, 'h': hook})
            self.trigger_hook(hook)
            LOG.info(_LI('Reached hook on %s'), six.text_type(self))
        while self.has_hook(hook) and self.status != self.FAILED:
            try:
                yield
            except Exception:
                self.clear_hook(hook)
                self._add_event(
                    self.action, self.status,
                    "Failure occured while waiting.")

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
        """Check to see if this resource is either mapped to resource_type
        or is a "resource_type".
        """
        if self.type() == resource_type:
            return True
        ri = self.stack.env.get_resource_info(self.type(),
                                              self.name)
        return ri.name == resource_type

    def implementation_signature(self):
        '''
        Return a tuple defining the implementation.

        This should be broken down into a definition and an
        implementation version.
        '''

        return (self.__class__.__name__, self.support_status.version)

    def identifier(self):
        '''Return an identifier for this resource.'''
        return identifier.ResourceIdentifier(resource_name=self.name,
                                             **self.stack.identifier())

    def parsed_template(self, section=None, default=None):
        '''
        Return the parsed template data for the resource. May be limited to
        only one section of the data, in which case a default value may also
        be supplied.
        '''
        default = default or {}
        if section is None:
            template = self.t
        else:
            template = self.t.get(section, default)
        return function.resolve(template)

    def frozen_definition(self):
        if self._stored_properties_data is not None:
            args = {'properties': self._stored_properties_data}
        else:
            args = {}
        return self.t.freeze(**args)

    def update_template_diff(self, after, before):
        '''
        Returns the difference between the before and after json snippets. If
        something has been removed in after which exists in before we set it to
        None.
        '''
        # Create a set containing the keys in both current and update template
        template_keys = set(before.keys())
        template_keys.update(set(after.keys()))

        # Create a set of keys which differ (or are missing/added)
        changed_keys_set = set([k for k in template_keys
                                if before.get(k) != after.get(k)])

        return dict((k, after.get(k)) for k in changed_keys_set)

    def update_template_diff_properties(self, after_props, before_props):
        '''
        Returns the changed Properties between the before and after properties.
        If any property having immutable as True is updated,
        raises NotSupported error.
        If any properties have changed which are not in
        update_allowed_properties, raises UpdateReplace.
        '''
        update_allowed_set = set(self.update_allowed_properties)
        immutable_set = set()
        for (psk, psv) in six.iteritems(self.properties.props):
            if psv.update_allowed():
                update_allowed_set.add(psk)
            if psv.immutable():
                immutable_set.add(psk)

        # Create a set of keys which differ (or are missing/added)
        changed_properties_set = set(k for k in after_props
                                     if before_props.get(k) !=
                                     after_props.get(k))

        # Create a list of updated properties offending property immutability
        update_replace_forbidden = [k for k in changed_properties_set
                                    if k in immutable_set]

        if update_replace_forbidden:
            mesg = _("Update to properties %(props)s of %(name)s (%(res)s)"
                     ) % {'props': ", ".join(sorted(update_replace_forbidden)),
                          'res': self.type(), 'name': self.name}
            raise exception.NotSupported(feature=mesg)

        if not changed_properties_set.issubset(update_allowed_set):
            raise UpdateReplace(self.name)

        return dict((k, after_props.get(k)) for k in changed_properties_set)

    def __str__(self):
        if self.stack.id:
            if self.resource_id:
                text = '%s "%s" [%s] %s' % (self.__class__.__name__, self.name,
                                            self.resource_id, str(self.stack))
            else:
                text = '%s "%s" %s' % (self.__class__.__name__, self.name,
                                       str(self.stack))
        else:
            text = '%s "%s"' % (self.__class__.__name__, self.name)
        return encodeutils.safe_encode(text)

    def __unicode__(self):
        if self.stack.id:
            if self.resource_id:
                text = '%s "%s" [%s] %s' % (self.__class__.__name__, self.name,
                                            self.resource_id,
                                            six.text_type(self.stack))
            else:
                text = '%s "%s" %s' % (self.__class__.__name__, self.name,
                                       six.text_type(self.stack))
        else:
            text = '%s "%s"' % (self.__class__.__name__, self.name)
        return encodeutils.safe_decode(text)

    def dep_attrs(self, resource_name):
        return self.t.dep_attrs(resource_name)

    def add_dependencies(self, deps):
        for dep in self.t.dependencies(self.stack):
            deps += (self, dep)
        deps += (self, None)

    def required_by(self):
        '''
        Returns a list of names of resources which directly require this
        resource as a dependency.
        '''
        return list(
            [r.name for r in self.stack.dependencies.required_by(self)])

    def client(self, name=None):
        client_name = name or self.default_client_name
        assert client_name, "Must specify client name"
        return self.stack.clients.client(client_name)

    def client_plugin(self, name=None):
        client_name = name or self.default_client_name
        assert client_name, "Must specify client name"
        return self.stack.clients.client_plugin(client_name)

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
        '''Return a context manager to record the progress of an action.

        Upon entering the context manager, the state is set to IN_PROGRESS.
        Upon exiting, the state will be set to COMPLETE if no exception was
        raised, or FAILED otherwise. Non-exit exceptions will be translated
        to ResourceFailure exceptions.

        Expected exceptions are re-raised, with the Resource left in the
        IN_PROGRESS state.
        '''
        try:
            self.state_set(action, self.IN_PROGRESS)
            yield
        except expected_exceptions as ex:
            with excutils.save_and_reraise_exception():
                LOG.debug('%s', six.text_type(ex))
        except Exception as ex:
            LOG.info('%(action)s: %(info)s', {"action": action,
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

    def action_handler_task(self, action, args=[], action_prefix=None):
        '''
        A task to call the Resource subclass's handler methods for an action.

        Calls the handle_<ACTION>() method for the given action and then calls
        the check_<ACTION>_complete() method with the result in a loop until it
        returns True. If the methods are not provided, the call is omitted.

        Any args provided are passed to the handler.

        If a prefix is supplied, the handler method handle_<PREFIX>_<ACTION>()
        is called instead.
        '''
        handler_action = action.lower()
        check = getattr(self, 'check_%s_complete' % handler_action, None)

        if action_prefix:
            handler_action = '%s_%s' % (action_prefix.lower(), handler_action)
        handler = getattr(self, 'handle_%s' % handler_action, None)

        if callable(handler):
            handler_data = handler(*args)
            yield
            if callable(check):
                while not check(handler_data):
                    yield

    @scheduler.wrappertask
    def _do_action(self, action, pre_func=None, resource_data=None):
        '''
        Perform a transition to a new state via a specified action
        action should be e.g self.CREATE, self.UPDATE etc, we set
        status based on this, the transition is handled by calling the
        corresponding handle_* and check_*_complete functions
        Note pre_func is an optional function reference which will
        be called before the handle_<action> function

        If the resource does not declare a check_$action_complete function,
        we declare COMPLETE status as soon as the handle_$action call has
        finished, and if no handle_$action function is declared, then we do
        nothing, useful e.g if the resource requires no action for a given
        state transition
        '''
        assert action in self.ACTIONS, 'Invalid action %s' % action

        with self._action_recorder(action):
            if callable(pre_func):
                pre_func()

            handler_args = [resource_data] if resource_data is not None else []
            yield self.action_handler_task(action, args=handler_args)

    def _update_stored_properties(self):
        self._stored_properties_data = function.resolve(self.properties.data)

    def preview(self):
        '''
        Default implementation of Resource.preview.

        This method should be overridden by child classes for specific
        behavior.
        '''
        return self

    @scheduler.wrappertask
    def create(self):
        '''
        Create the resource. Subclasses should provide a handle_create() method
        to customise creation.
        '''
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
        # are __init__'d, but before they are create()'d)
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
                    return
                else:
                    action = self.CREATE
            except exception.ResourceFailure as failure:
                if not isinstance(failure.exc, ResourceInError):
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
        '''
        Adopt the existing resource. Resource subclasses can provide
        a handle_adopt() method to customise adopt.
        '''
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

    def _get_resource_info(self, resource_data):
        if not resource_data:
            return None, None, None

        return (resource_data.get('resource_id'),
                resource_data.get('resource_data'),
                resource_data.get('metadata'))

    def _needs_update(self, after, before, after_props, before_props,
                      prev_resource):
        if self.status == self.FAILED or \
                (self.action == self.INIT and self.status == self.COMPLETE):
            raise UpdateReplace(self)

        if prev_resource is not None:
            cur_class_def, cur_ver = self.implementation_signature()
            prev_class_def, prev_ver = prev_resource.implementation_signature()

            if prev_class_def != cur_class_def:
                raise UpdateReplace(self.name)
            if prev_ver != cur_ver:
                return True

        if before != after.freeze():
            return True

        try:
            return before_props != after_props
        except ValueError:
            return True

    @scheduler.wrappertask
    def update(self, after, before=None, prev_resource=None):
        '''
        update the resource. Subclasses should provide a handle_update() method
        to customise update, the base-class handle_update will fail by default.
        '''
        action = self.UPDATE

        assert isinstance(after, rsrc_defn.ResourceDefinition)

        if before is None:
            before = self.frozen_definition()

        before_props = before.properties(self.properties_schema,
                                         self.context)
        # Regenerate the schema, else validation would fail
        self.regenerate_info_schema(after)
        after_props = after.properties(self.properties_schema,
                                       self.context)

        yield self._break_if_required(
            self.UPDATE, environment.HOOK_PRE_UPDATE)

        if not self._needs_update(after, before, after_props, before_props,
                                  prev_resource):
            return

        if (self.action, self.status) in ((self.CREATE, self.IN_PROGRESS),
                                          (self.UPDATE, self.IN_PROGRESS),
                                          (self.ADOPT, self.IN_PROGRESS)):
            exc = Exception(_('Resource update already requested'))
            raise exception.ResourceFailure(exc, self, action)

        LOG.info(_LI('updating %s'), six.text_type(self))

        self.updated_time = datetime.utcnow()
        with self._action_recorder(action, UpdateReplace):
            after_props.validate()
            tmpl_diff = self.update_template_diff(function.resolve(after),
                                                  before)
            prop_diff = self.update_template_diff_properties(after_props,
                                                             before_props)
            yield self.action_handler_task(action,
                                           args=[after, tmpl_diff, prop_diff])

            self.t = after
            self.reparse()
            self._update_stored_properties()

    def check(self):
        """Checks that the physical resource is in its expected state

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
        '''
        Suspend the resource.  Subclasses should provide a handle_suspend()
        method to implement suspend
        '''
        action = self.SUSPEND

        # Don't try to suspend the resource unless it's in a stable state
        if (self.action == self.DELETE or self.status != self.COMPLETE):
            exc = exception.Error(_('State %s invalid for suspend')
                                  % six.text_type(self.state))
            raise exception.ResourceFailure(exc, self, action)

        LOG.info(_LI('suspending %s'), six.text_type(self))
        return self._do_action(action)

    def resume(self):
        '''
        Resume the resource.  Subclasses should provide a handle_resume()
        method to implement resume
        '''
        action = self.RESUME

        # Can't resume a resource unless it's SUSPEND_COMPLETE
        if self.state != (self.SUSPEND, self.COMPLETE):
            exc = exception.Error(_('State %s invalid for resume')
                                  % six.text_type(self.state))
            raise exception.ResourceFailure(exc, self, action)

        LOG.info(_LI('resuming %s'), six.text_type(self))
        return self._do_action(action)

    def snapshot(self):
        '''Snapshot the resource and return the created data, if any.'''
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
        '''
        Reduce length of physical resource name to a limit.

        The reduced name will consist of the following:

        * the first 2 characters of the name
        * a hyphen
        * the end of the name, truncated on the left to bring
          the name length within the limit

        :param name: The name to reduce the length of
        :param limit: The max length limit
        :returns: A name whose length is less than or equal to the limit
        '''
        if len(name) <= limit:
            return name

        if limit < 4:
            raise ValueError(_('limit cannot be less than 4'))

        postfix_length = limit - 3
        return name[0:2] + '-' + name[-postfix_length:]

    def validate(self):
        LOG.info(_LI('Validating %s'), six.text_type(self))

        function.validate(self.t)
        self.validate_deletion_policy(self.t.deletion_policy())
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

    @scheduler.wrappertask
    def delete(self):
        '''
        Delete the resource. Subclasses should provide a handle_delete() method
        to customise deletion.
        '''
        action = self.DELETE

        if (self.action, self.status) == (self.DELETE, self.COMPLETE):
            return
        # No need to delete if the resource has never been created
        if self.action == self.INIT:
            return

        initial_state = self.state

        LOG.info(_LI('deleting %s'), six.text_type(self))

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

    @scheduler.wrappertask
    def destroy(self):
        '''
        Delete the resource and remove it from the database.
        '''
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
                rs = resource_objects.Resource.get_obj(self.context, self.id)
                rs.update_and_save({'nova_instance': self.resource_id})
            except Exception as ex:
                LOG.warn(_LW('db error %s'), ex)

    def _store(self, metadata=None):
        '''Create the resource in the database.'''
        try:
            rs = {'action': self.action,
                  'status': self.status,
                  'status_reason': self.status_reason,
                  'stack_id': self.stack.id,
                  'nova_instance': self.resource_id,
                  'name': self.name,
                  'rsrc_metadata': metadata,
                  'properties_data': self._stored_properties_data,
                  'needed_by': self.needed_by,
                  'requires': self.requires,
                  'replaces': self.replaces,
                  'replaced_by': self.replaced_by,
                  'current_template_id': self.current_template_id,
                  'stack_name': self.stack.name}

            new_rs = resource_objects.Resource.create(self.context, rs)
            self.id = new_rs.id
            self.uuid = new_rs.uuid
            self.created_time = new_rs.created_at
            self._rsrc_metadata = metadata
        except Exception as ex:
            LOG.error(_LE('DB error %s'), ex)

    def _add_event(self, action, status, reason):
        '''Add a state change event to the database.'''
        ev = event.Event(self.context, self.stack, action, status, reason,
                         self.resource_id, self.properties,
                         self.name, self.type())

        ev.store()

    def _store_or_update(self, action, status, reason):
        prev_action = self.action
        self.action = action
        self.status = status
        self.status_reason = reason

        data = {
            'action': self.action,
            'status': self.status,
            'status_reason': reason,
            'stack_id': self.stack.id,
            'updated_at': self.updated_time,
            'properties_data': self._stored_properties_data,
            'needed_by': self.needed_by,
            'requires': self.requires,
            'replaces': self.replaces,
            'replaced_by': self.replaced_by,
            'current_template_id': self.current_template_id,
            'nova_instance': self.resource_id
        }
        if prev_action == self.INIT:
            metadata = self.t.metadata()
            data['rsrc_metadata'] = metadata
        else:
            metadata = self._rsrc_metadata

        if self.id is not None:
            try:
                rs = resource_objects.Resource.get_obj(self.context, self.id)
                rs.update_and_save(data)
            except Exception as ex:
                LOG.error(_LE('DB error %s'), ex)
            else:
                self._rsrc_metadata = metadata
        else:
            # This should only happen in unit tests
            LOG.warning(_LW('Resource "%s" not pre-stored in DB'), self)
            self._store(metadata)

    def _resolve_attribute(self, name):
        """
        Default implementation; should be overridden by resources that expose
        attributes

        :param name: The attribute to resolve
        :returns: the resource attribute named key
        """
        # By default, no attributes resolve
        pass

    def regenerate_info_schema(self, definition):
        """
        Default implementation; should be overridden by resources that would
        require schema refresh during update, ex. TemplateResource

        :definition: Resource Definition
        """
        # By default, do not regenerate
        pass

    def state_reset(self):
        """
        Reset state to (INIT, COMPLETE)
        """
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
        '''Returns state, tuple of action, status.'''
        return (self.action, self.status)

    def FnGetRefId(self):
        '''
        For the intrinsic function Ref.

        :results: the id or name of the resource.
        '''
        if self.resource_id is not None:
            return six.text_type(self.resource_id)
        else:
            return six.text_type(self.name)

    def physical_resource_name_or_FnGetRefId(self):
        res_name = self.physical_resource_name()
        if res_name is not None:
            return six.text_type(res_name)
        else:
            return Resource.FnGetRefId(self)

    def FnGetAtt(self, key, *path):
        '''
        For the intrinsic function Fn::GetAtt.

        :param key: the attribute key.
        :param path: a list of path components to select from the attribute.
        :returns: the attribute value.
        '''
        try:
            attribute = self.attributes[key]
        except KeyError:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)
        else:
            return attributes.select_from_attribute(attribute, path)

    def FnBase64(self, data):
        '''
        For the instrinsic function Fn::Base64.

        :param data: the input data.
        :returns: the Base64 representation of the input data.
        '''
        return base64.b64encode(data)

    def signal(self, details=None):
        '''
        signal the resource. Subclasses should provide a handle_signal() method
        to implement the signal, the base-class raise an exception if no
        handler is implemented.
        '''
        if self.action in self.no_signal_actions:
            self._add_event(self.action, self.status,
                            'Cannot signal resource during %s' % self.action)
            ex = Exception(_('Cannot signal resource during %s') % self.action)
            raise exception.ResourceFailure(ex, self)

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

        # Clear the hook without interfering with resources'
        # `handle_signal` callbacks:
        if (details and 'unset_hook' in details and
                environment.valid_hook_type(details.get('unset_hook'))):
            hook = details['unset_hook']
            if self.has_hook(hook):
                self.clear_hook(hook)
                LOG.info(_LI('Clearing %(hook)s hook on %(resource)s'),
                         {'hook': hook, 'resource': six.text_type(self)})
                self._add_event(self.action, self.status,
                                "Hook %s is cleared" % hook)
                return

        if not callable(getattr(self, 'handle_signal', None)):
            raise exception.ResourceActionNotSupported(action='signal')

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
            LOG.exception(_LE('signal %(name)s : %(msg)s')
                          % {'name': six.text_type(self), 'msg': ex})
            failure = exception.ResourceFailure(ex, self)
            raise failure

    def handle_update(self, json_snippet=None, tmpl_diff=None, prop_diff=None):
        if prop_diff:
            raise UpdateReplace(self.name)

    def metadata_update(self, new_metadata=None):
        '''
        No-op for resources which don't explicitly override this method
        '''
        if new_metadata:
            LOG.warn(_LW("Resource %s does not implement metadata update"),
                     self.name)

    @classmethod
    def resource_to_template(cls, resource_type):
        '''
        :param resource_type: The resource type to be displayed in the template
        :returns: A template where the resource's properties_schema is mapped
            as parameters, and the resource's attributes_schema is mapped as
            outputs
        '''
        schema = cls.properties_schema
        params, props = (properties.Properties.
                         schema_to_parameters_and_properties(schema))

        resource_name = cls.__name__
        return {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': params,
            'Resources': {
                resource_name: {
                    'Type': resource_type,
                    'Properties': props
                }
            },
            'Outputs': attributes.Attributes.as_outputs(resource_name, cls)
        }

    def data(self):
        '''
        Resource data for this resource

        Use methods data_set and data_delete to modify the resource data
        for this resource.

        :returns: a dict representing the resource data for this resource.
        '''
        if self._data is None and self.id:
            try:
                self._data = resource_data_objects.ResourceData.get_all(self)
            except exception.NotFound:
                pass

        return self._data or {}

    def data_set(self, key, value, redact=False):
        '''Save resource's key/value pair to database.'''
        resource_data_objects.ResourceData.set(self, key, value, redact)
        # force fetch all resource data from the database again
        self._data = None

    def data_delete(self, key):
        '''
        Remove a resource_data element associated to a resource.

        :returns: True if the key existed to delete
        '''
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
