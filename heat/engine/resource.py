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
from datetime import datetime
from oslo.config import cfg
import six
import warnings

from heat.common import exception
from heat.common import identifier
from heat.common import short_id
from heat.common import timeutils
from heat.db import api as db_api
from heat.engine import attributes
from heat.engine import environment
from heat.engine import event
from heat.engine import function
from heat.engine.properties import Properties
from heat.engine import resources
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import support
from heat.openstack.common import excutils
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

cfg.CONF.import_opt('action_retry_limit', 'heat.common.config')

LOG = logging.getLogger(__name__)


def get_types(support_status):
    '''Return a list of valid resource types.'''
    return resources.global_env().get_types(support_status)


def get_class(resource_type, resource_name=None):
    '''Return the Resource class for a given resource type.'''
    return resources.global_env().get_class(resource_type, resource_name)


def _register_class(resource_type, resource_class):
    resources.global_env().register_class(resource_type, resource_class)


class UpdateReplace(Exception):
    '''Raised when resource update requires replacement.'''
    def __init__(self, resource_name='Unknown'):
        msg = _("The Resource %s requires replacement.") % resource_name
        super(Exception, self).__init__(six.text_type(msg))


class ResourceInError(exception.HeatException):
    msg_fmt = _('Went to status %(resource_status)s '
                'due to "%(status_reason)s"')

    def __init__(self, status_reason=_('Unknown'), **kwargs):
        super(ResourceInError, self).__init__(status_reason=status_reason,
                                              **kwargs)


class ResourceUnknownStatus(exception.HeatException):
    msg_fmt = _('Unknown status %(resource_status)s')


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

    def __new__(cls, name, definition, stack):
        '''Create a new Resource of the appropriate class for its type.'''

        assert isinstance(definition, rsrc_defn.ResourceDefinition)

        if cls != Resource:
            # Call is already for a subclass, so pass it through
            ResourceClass = cls
        else:
            from heat.engine.resources import template_resource
            # Select the correct subclass to instantiate.

            # Note: If the current stack is an implementation of
            # a resource type (a TemplateResource mapped in the environment)
            # then don't infinitely recurse by creating a child stack
            # of the same type. Instead get the next match which will get
            # us closer to a concrete class.
            def get_ancestor_template_resources():
                """Return an ancestry list (TemplateResources only)."""
                parent = stack.parent_resource
                while parent is not None:
                    if isinstance(parent, template_resource.TemplateResource):
                        yield parent.template_name
                    parent = parent.stack.parent_resource

            ancestor_list = set(get_ancestor_template_resources())

            def accept_class(res_info):
                if not isinstance(res_info, environment.TemplateResourceInfo):
                    return True
                return res_info.template_name not in ancestor_list

            registry = stack.env.registry
            ResourceClass = registry.get_class(definition.resource_type,
                                               resource_name=name,
                                               accept_fn=accept_class)
            assert issubclass(ResourceClass, Resource)

        return super(Resource, cls).__new__(ResourceClass)

    def __init__(self, name, definition, stack):
        if '/' in name:
            raise ValueError(_('Resource name may not contain "/"'))

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
        self._data = {}
        self._rsrc_metadata = None
        self._stored_properties_data = None
        self.created_time = None
        self.updated_time = None

        resource = stack.db_resource_get(name)
        if resource:
            self._load_data(resource)

    def _load_data(self, resource):
        '''Load the resource state from its DB representation.'''
        self.resource_id = resource.nova_instance
        self.action = resource.action
        self.status = resource.status
        self.status_reason = resource.status_reason
        self.id = resource.id
        try:
            self._data = db_api.resource_data_get_all(self, resource.data)
        except exception.NotFound:
            self._data = {}
        self._rsrc_metadata = resource.rsrc_metadata
        self._stored_properties_data = resource.properties_data
        self.created_time = resource.created_at
        self.updated_time = resource.updated_at

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
        if self.id is None:
            return self.t.metadata()
        if self._rsrc_metadata is not None:
            return self._rsrc_metadata
        rs = db_api.resource_get(self.stack.context, self.id)
        rs.refresh(attrs=['rsrc_metadata'])
        self._rsrc_metadata = rs.rsrc_metadata
        return rs.rsrc_metadata

    def metadata_set(self, metadata):
        if self.id is None:
            raise exception.ResourceNotAvailable(resource_name=self.name)
        rs = db_api.resource_get(self.stack.context, self.id)
        rs.update_and_save({'rsrc_metadata': metadata})
        self._rsrc_metadata = metadata

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
                return '%s "%s" [%s] %s' % (self.__class__.__name__, self.name,
                                            self.resource_id, str(self.stack))
            return '%s "%s" %s' % (self.__class__.__name__, self.name,
                                   str(self.stack))
        return '%s "%s"' % (self.__class__.__name__, self.name)

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
                                              "info": str(self)},
                     exc_info=True)
            failure = exception.ResourceFailure(ex, self, action)
            self.state_set(action, self.FAILED, six.text_type(failure))
            raise failure
        except:  # noqa
            with excutils.save_and_reraise_exception():
                try:
                    self.state_set(action, self.FAILED, '%s aborted' % action)
                except Exception:
                    LOG.exception(_('Error marking resource as failed'))
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
                                  % str(self.state))
            raise exception.ResourceFailure(exc, self, action)

        LOG.info(_('creating %s') % str(self))

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

    @scheduler.wrappertask
    def update(self, after, before=None, prev_resource=None):
        '''
        update the resource. Subclasses should provide a handle_update() method
        to customise update, the base-class handle_update will fail by default.
        '''
        action = self.UPDATE

        assert isinstance(after, rsrc_defn.ResourceDefinition)

        (cur_class_def, cur_ver) = self.implementation_signature()
        prev_ver = cur_ver
        if prev_resource is not None:
            (prev_class_def,
             prev_ver) = prev_resource.implementation_signature()
            if prev_class_def != cur_class_def:
                raise UpdateReplace(self.name)

        if before is None:
            before = self.parsed_template()
        if prev_ver == cur_ver and before == after:
            return

        if (self.action, self.status) in ((self.CREATE, self.IN_PROGRESS),
                                          (self.UPDATE, self.IN_PROGRESS),
                                          (self.ADOPT, self.IN_PROGRESS)):
            exc = Exception(_('Resource update already requested'))
            raise exception.ResourceFailure(exc, self, action)

        LOG.info(_('updating %s') % str(self))

        self.updated_time = datetime.utcnow()
        with self._action_recorder(action, UpdateReplace):
            before_properties = Properties(self.properties_schema,
                                           before.get('Properties', {}),
                                           function.resolve,
                                           self.name,
                                           self.context)
            after_properties = after.properties(self.properties_schema,
                                                self.context)
            after_properties.validate()
            tmpl_diff = self.update_template_diff(function.resolve(after),
                                                  before)
            prop_diff = self.update_template_diff_properties(after_properties,
                                                             before_properties)
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
        LOG.info(_('Checking %s') % six.text_type(self))

        if hasattr(self, 'handle_%s' % action.lower()):
            return self._do_action(action)
        else:
            reason = '%s not supported for %s' % (action, self.type())
            self.state_set(action, self.COMPLETE, reason)

    def suspend(self):
        '''
        Suspend the resource.  Subclasses should provide a handle_suspend()
        method to implement suspend
        '''
        action = self.SUSPEND

        # Don't try to suspend the resource unless it's in a stable state
        if (self.action == self.DELETE or self.status != self.COMPLETE):
            exc = exception.Error(_('State %s invalid for suspend')
                                  % str(self.state))
            raise exception.ResourceFailure(exc, self, action)

        LOG.info(_('suspending %s') % str(self))
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
                                  % str(self.state))
            raise exception.ResourceFailure(exc, self, action)

        LOG.info(_('resuming %s') % str(self))
        return self._do_action(action)

    def snapshot(self):
        '''Snapshot the resource and return the created data, if any.'''
        LOG.info(_('snapshotting %s') % str(self))
        return self._do_action(self.SNAPSHOT)

    def delete_snapshot(self, data):
        handle_delete_snapshot = getattr(
            self, 'handle_delete_snapshot', None)
        if callable(handle_delete_snapshot):
            handle_data = handle_delete_snapshot(data)
            check = getattr(self, 'check_delete_snapshot_complete', None)
            if callable(check):
                while not check(handle_data):
                    yield

    def physical_resource_name(self):
        if self.id is None:
            return None

        name = '%s-%s-%s' % (self.stack.name,
                             self.name,
                             short_id.get_id(self.id))

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
        LOG.info(_('Validating %s') % str(self))

        function.validate(self.t)
        self.validate_deletion_policy(self.t.deletion_policy())
        return self.properties.validate()

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

        LOG.info(_('deleting %s') % str(self))

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
            db_api.resource_get(self.context, self.id).delete()
        except exception.NotFound:
            # Don't fail on delete if the db entry has
            # not been created yet.
            pass

        self.id = None

    def resource_id_set(self, inst):
        self.resource_id = inst
        if self.id is not None:
            try:
                rs = db_api.resource_get(self.context, self.id)
                rs.update_and_save({'nova_instance': self.resource_id})
            except Exception as ex:
                LOG.warn(_('db error %s') % ex)

    def _store(self):
        '''Create the resource in the database.'''
        metadata = self.metadata_get()
        try:
            rs = {'action': self.action,
                  'status': self.status,
                  'status_reason': self.status_reason,
                  'stack_id': self.stack.id,
                  'nova_instance': self.resource_id,
                  'name': self.name,
                  'rsrc_metadata': metadata,
                  'properties_data': self._stored_properties_data,
                  'stack_name': self.stack.name}

            new_rs = db_api.resource_create(self.context, rs)
            self.id = new_rs.id
            self.created_time = new_rs.created_at
            self._rsrc_metadata = metadata
        except Exception as ex:
            LOG.error(_('DB error %s') % ex)

    def _add_event(self, action, status, reason):
        '''Add a state change event to the database.'''
        ev = event.Event(self.context, self.stack, action, status, reason,
                         self.resource_id, self.properties,
                         self.name, self.type())

        ev.store()

    def _store_or_update(self, action, status, reason):
        self.action = action
        self.status = status
        self.status_reason = reason

        if self.id is not None:
            try:
                rs = db_api.resource_get(self.context, self.id)
                rs.update_and_save({'action': self.action,
                                    'status': self.status,
                                    'status_reason': reason,
                                    'stack_id': self.stack.id,
                                    'updated_at': self.updated_time,
                                    'nova_instance': self.resource_id})
            except Exception as ex:
                LOG.error(_('DB error %s') % ex)

        # store resource in DB on transition to CREATE_IN_PROGRESS
        # all other transitions (other than to DELETE_COMPLETE)
        # should be handled by the update_and_save above..
        elif (action, status) in [(self.CREATE, self.IN_PROGRESS),
                                  (self.ADOPT, self.IN_PROGRESS)]:
            self._store()

    def _resolve_attribute(self, name):
        """
        Default implementation; should be overridden by resources that expose
        attributes

        :param name: The attribute to resolve
        :returns: the resource attribute named key
        """
        # By default, no attributes resolve
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
            return unicode(self.resource_id)
        else:
            return unicode(self.name)

    def physical_resource_name_or_FnGetRefId(self):
        res_name = self.physical_resource_name()
        if res_name is not None:
            return unicode(res_name)
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
        def get_string_details():
            if details is None:
                return 'No signal details provided'
            if isinstance(details, basestring):
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
        if not callable(getattr(self, 'handle_signal', None)):
            raise exception.ResourceActionNotSupported(action='signal')

        try:
            signal_result = self.handle_signal(details)
            if signal_result:
                reason_string = "Signal: %s" % signal_result
            else:
                reason_string = get_string_details()
            self._add_event('signal', self.status, reason_string)
        except Exception as ex:
            LOG.exception(_('signal %(name)s : %(msg)s') % {'name': str(self),
                                                            'msg': ex})
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
            LOG.warning(_("Resource %s does not implement metadata update")
                        % self.name)

    @classmethod
    def resource_to_template(cls, resource_type):
        '''
        :param resource_type: The resource type to be displayed in the template
        :returns: A template where the resource's properties_schema is mapped
            as parameters, and the resource's attributes_schema is mapped as
            outputs
        '''
        (parameters, properties) = (Properties.
                                    schema_to_parameters_and_properties(
                                        cls.properties_schema))

        resource_name = cls.__name__
        return {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': parameters,
            'Resources': {
                resource_name: {
                    'Type': resource_type,
                    'Properties': properties
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
                self._data = db_api.resource_data_get_all(self)
            except exception.NotFound:
                pass

        return self._data or {}

    def data_set(self, key, value, redact=False):
        '''Save resource's key/value pair to database.'''
        db_api.resource_data_set(self, key, value, redact)
        # force fetch all resource data from the database again
        self._data = None

    def data_delete(self, key):
        '''
        Remove a resource_data element associated to a resource.

        :returns: True if the key existed to delete
        '''
        try:
            db_api.resource_data_delete(self, key)
        except exception.NotFound:
            return False
        else:
            # force fetch all resource data from the database again
            self._data = None
            return True
