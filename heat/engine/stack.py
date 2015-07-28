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
import copy
from datetime import datetime
import re
import warnings

from oslo.config import cfg
from oslo.utils import encodeutils
import six

from heat.common import context as common_context
from heat.common import environment_format as env_fmt
from heat.common import exception
from heat.common.exception import StackValidationFailed
from heat.common.i18n import _
from heat.common import identifier
from heat.common import lifecycle_plugin_utils
from heat.db import api as db_api
from heat.engine import dependencies
from heat.engine import environment
from heat.engine import function
from heat.engine.notification import stack as notification
from heat.engine.parameter_groups import ParameterGroups
from heat.engine import resource
from heat.engine import resources
from heat.engine import scheduler
from heat.engine.template import Template
from heat.engine import update
from heat.openstack.common import log as logging
from heat.rpc import api as rpc_api

LOG = logging.getLogger(__name__)

ERROR_WAIT_TIME = 240


class ForcedCancel(BaseException):
    """Exception raised to cancel task execution."""

    def __str__(self):
        return "Operation cancelled"


class Stack(collections.Mapping):

    ACTIONS = (
        CREATE, DELETE, UPDATE, ROLLBACK, SUSPEND,
        RESUME, ADOPT, SNAPSHOT, CHECK,
    ) = (
        'CREATE', 'DELETE', 'UPDATE', 'ROLLBACK', 'SUSPEND',
        'RESUME', 'ADOPT', 'SNAPSHOT', 'CHECK',
    )

    STATUSES = (IN_PROGRESS, FAILED, COMPLETE
                ) = ('IN_PROGRESS', 'FAILED', 'COMPLETE')

    _zones = None

    def __init__(self, context, stack_name, tmpl, env=None,
                 stack_id=None, action=None, status=None,
                 status_reason='', timeout_mins=None, resolve_data=True,
                 disable_rollback=True, parent_resource=None, owner_id=None,
                 adopt_stack_data=None, stack_user_project_id=None,
                 created_time=None, updated_time=None,
                 user_creds_id=None, tenant_id=None,
                 use_stored_context=False, username=None):
        '''
        Initialise from a context, name, Template object and (optionally)
        Environment object. The database ID may also be initialised, if the
        stack is already in the database.
        '''

        def _validate_stack_name(name):
            if not re.match("[a-zA-Z][a-zA-Z0-9_.-]*$", name):
                message = _('Invalid stack name %s must contain '
                            'only alphanumeric or \"_-.\" characters, '
                            'must start with alpha') % name
                raise exception.StackValidationFailed(message=message)

        if owner_id is None:
            _validate_stack_name(stack_name)

        self.id = stack_id
        self.owner_id = owner_id
        self.context = context
        self.t = tmpl
        self.name = stack_name
        self.action = self.CREATE if action is None else action
        self.status = self.IN_PROGRESS if status is None else status
        self.status_reason = status_reason
        self.timeout_mins = timeout_mins
        self.disable_rollback = disable_rollback
        self.parent_resource = parent_resource
        self._resources = None
        self._dependencies = None
        self._access_allowed_handlers = {}
        self._db_resources = None
        self.adopt_stack_data = adopt_stack_data
        self.stack_user_project_id = stack_user_project_id
        self.created_time = created_time
        self.updated_time = updated_time
        self.user_creds_id = user_creds_id

        if use_stored_context:
            self.context = self.stored_context()

        self.clients = self.context.clients

        # This will use the provided tenant ID when loading the stack
        # from the DB or get it from the context for new stacks.
        self.tenant_id = tenant_id or self.context.tenant_id
        self.username = username or self.context.username

        resources.initialise()

        self.env = env or environment.Environment({})
        self.parameters = self.t.parameters(self.identifier(),
                                            user_params=self.env.params)
        self._set_param_stackid()

        if resolve_data:
            self.outputs = self.resolve_static_data(self.t[self.t.OUTPUTS])
        else:
            self.outputs = {}

    def stored_context(self):
        if self.user_creds_id:
            creds = db_api.user_creds_get(self.user_creds_id)
            # Maintain request_id from self.context so we retain traceability
            # in situations where servicing a request requires switching from
            # the request context to the stored context
            creds['request_id'] = self.context.request_id
            # We don't store roles in the user_creds table, so disable the
            # policy check for admin by setting is_admin=False.
            creds['is_admin'] = False
            return common_context.RequestContext.from_dict(creds)
        else:
            msg = _("Attempt to use stored_context with no user_creds")
            raise exception.Error(msg)

    @property
    def resources(self):
        if self._resources is None:
            self._resources = dict((name, resource.Resource(name, data, self))
                                   for (name, data) in
                                   self.t.resource_definitions(self).items())
            # There is no need to continue storing the db resources
            # after resource creation
            self._db_resources = None
        return self._resources

    def iter_resources(self, nested_depth=0):
        '''
        Iterates over all the resources in a stack, including nested stacks up
        to `nested_depth` levels below.
        '''
        for res in self.values():
            yield res

            get_nested = getattr(res, 'nested', None)
            if not callable(get_nested) or nested_depth == 0:
                continue

            nested_stack = get_nested()
            if nested_stack is None:
                continue

            for nested_res in nested_stack.iter_resources(nested_depth - 1):
                yield nested_res

    def db_resource_get(self, name):
        if not self.id:
            return None
        if self._db_resources is None:
            try:
                self._db_resources = db_api.resource_get_all_by_stack(
                    self.context, self.id)
            except exception.NotFound:
                return None
        return self._db_resources.get(name)

    @property
    def dependencies(self):
        if self._dependencies is None:
            self._dependencies = self._get_dependencies(
                self.resources.itervalues())
        return self._dependencies

    def reset_dependencies(self):
        self._dependencies = None

    @property
    def root_stack(self):
        '''
        Return the root stack if this is nested (otherwise return self).
        '''
        if (self.parent_resource and self.parent_resource.stack):
            return self.parent_resource.stack.root_stack
        return self

    def total_resources(self):
        '''
        Return the total number of resources in a stack, including nested
        stacks below.
        '''
        def total_nested(res):
            get_nested = getattr(res, 'nested', None)
            if callable(get_nested):
                nested_stack = get_nested()
                if nested_stack is not None:
                    return nested_stack.total_resources()
            return 0

        return len(self) + sum(total_nested(res) for res in self.itervalues())

    def _set_param_stackid(self):
        '''
        Update self.parameters with the current ARN which is then provided
        via the Parameters class as the StackId pseudo parameter
        '''
        if not self.parameters.set_stack_id(self.identifier()):
            LOG.warning(_("Unable to set parameters StackId identifier"))

    @staticmethod
    def _get_dependencies(resources):
        '''Return the dependency graph for a list of resources.'''
        deps = dependencies.Dependencies()
        for resource in resources:
            resource.add_dependencies(deps)

        return deps

    @classmethod
    def load(cls, context, stack_id=None, stack=None, parent_resource=None,
             show_deleted=True, use_stored_context=False):
        '''Retrieve a Stack from the database.'''
        if stack is None:
            stack = db_api.stack_get(context, stack_id,
                                     show_deleted=show_deleted,
                                     eager_load=True)
        if stack is None:
            message = _('No stack exists with id "%s"') % str(stack_id)
            raise exception.NotFound(message)

        return cls._from_db(context, stack, parent_resource=parent_resource,
                            use_stored_context=use_stored_context)

    @classmethod
    def load_all(cls, context, limit=None, marker=None, sort_keys=None,
                 sort_dir=None, filters=None, tenant_safe=True,
                 show_deleted=False, resolve_data=True,
                 show_nested=False):
        stacks = db_api.stack_get_all(context, limit, sort_keys, marker,
                                      sort_dir, filters, tenant_safe,
                                      show_deleted, show_nested) or []
        for stack in stacks:
            yield cls._from_db(context, stack, resolve_data=resolve_data)

    @classmethod
    def _from_db(cls, context, stack, parent_resource=None, resolve_data=True,
                 use_stored_context=False):
        template = Template.load(
            context, stack.raw_template_id, stack.raw_template)
        env = environment.Environment(stack.parameters)
        return cls(context, stack.name, template, env,
                   stack.id, stack.action, stack.status, stack.status_reason,
                   stack.timeout, resolve_data, stack.disable_rollback,
                   parent_resource, owner_id=stack.owner_id,
                   stack_user_project_id=stack.stack_user_project_id,
                   created_time=stack.created_at,
                   updated_time=stack.updated_at,
                   user_creds_id=stack.user_creds_id, tenant_id=stack.tenant,
                   use_stored_context=use_stored_context,
                   username=stack.username)

    def store(self, backup=False):
        '''
        Store the stack in the database and return its ID
        If self.id is set, we update the existing stack
        '''
        s = {
            'name': self._backup_name() if backup else self.name,
            'raw_template_id': self.t.store(self.context),
            'parameters': self.env.user_env_as_dict(),
            'owner_id': self.owner_id,
            'username': self.username,
            'tenant': self.tenant_id,
            'action': self.action,
            'status': self.status,
            'status_reason': self.status_reason,
            'timeout': self.timeout_mins,
            'disable_rollback': self.disable_rollback,
            'stack_user_project_id': self.stack_user_project_id,
            'updated_at': self.updated_time,
            'user_creds_id': self.user_creds_id,
            'backup': backup
        }
        if self.id:
            db_api.stack_update(self.context, self.id, s)
        else:
            if not self.user_creds_id:
                # Create a context containing a trust_id and trustor_user_id
                # if trusts are enabled
                if cfg.CONF.deferred_auth_method == 'trusts':
                    keystone = self.clients.client('keystone')
                    trust_ctx = keystone.create_trust_context()
                    new_creds = db_api.user_creds_create(trust_ctx)
                else:
                    new_creds = db_api.user_creds_create(self.context)
                s['user_creds_id'] = new_creds.id
                self.user_creds_id = new_creds.id

            new_s = db_api.stack_create(self.context, s)
            self.id = new_s.id
            self.created_time = new_s.created_at

        self._set_param_stackid()

        return self.id

    def _backup_name(self):
        return '%s*' % self.name

    def identifier(self):
        '''
        Return an identifier for this stack.
        '''
        return identifier.HeatIdentifier(self.tenant_id, self.name, self.id)

    def __iter__(self):
        '''
        Return an iterator over the resource names.
        '''
        return iter(self.resources)

    def __len__(self):
        '''Return the number of resources.'''
        return len(self.resources)

    def __getitem__(self, key):
        '''Get the resource with the specified name.'''
        return self.resources[key]

    def add_resource(self, resource):
        '''Insert the given resource into the stack.'''
        template = resource.stack.t
        resource.stack = self
        definition = resource.t.reparse(self, template)
        resource.t = definition
        resource.reparse()
        self.resources[resource.name] = resource
        self.t.add_resource(definition)
        if self.t.id is not None:
            self.t.store(self.context)

    def remove_resource(self, resource_name):
        '''Remove the resource with the specified name.'''
        del self.resources[resource_name]
        self.t.remove_resource(resource_name)
        if self.t.id is not None:
            self.t.store(self.context)

    def __contains__(self, key):
        '''Determine whether the stack contains the specified resource.'''
        if self._resources is not None:
            return key in self.resources
        else:
            return key in self.t[self.t.RESOURCES]

    def __eq__(self, other):
        '''
        Compare two Stacks for equality.

        Stacks are considered equal only if they are identical.
        '''
        return self is other

    def __str__(self):
        '''Return a human-readable string representation of the stack.'''
        return 'Stack "%s" [%s]' % (self.name, self.id)

    def resource_by_refid(self, refid):
        '''
        Return the resource in this stack with the specified
        refid, or None if not found
        '''
        for r in self.values():
            if r.state in (
                    (r.INIT, r.COMPLETE),
                    (r.CREATE, r.IN_PROGRESS),
                    (r.CREATE, r.COMPLETE),
                    (r.RESUME, r.IN_PROGRESS),
                    (r.RESUME, r.COMPLETE),
                    (r.UPDATE, r.IN_PROGRESS),
                    (r.UPDATE, r.COMPLETE)) and r.FnGetRefId() == refid:
                return r

    def register_access_allowed_handler(self, credential_id, handler):
        '''
        Register a function which determines whether the credentials with
        a give ID can have access to a named resource.
        '''
        assert callable(handler), 'Handler is not callable'
        self._access_allowed_handlers[credential_id] = handler

    def access_allowed(self, credential_id, resource_name):
        '''
        Returns True if the credential_id is authorised to access the
        resource with the specified resource_name.
        '''
        if not self.resources:
            # this also triggers lazy-loading of resources
            # so is required for register_access_allowed_handler
            # to be called
            return False

        handler = self._access_allowed_handlers.get(credential_id)
        return handler and handler(resource_name)

    def validate(self):
        '''
        Validates the template.
        '''
        # TODO(sdake) Should return line number of invalid reference

        # validate overall template (top-level structure)
        self.t.validate()

        # Validate parameters
        self.parameters.validate(context=self.context)

        # Validate Parameter Groups
        parameter_groups = ParameterGroups(self.t)
        parameter_groups.validate()

        # Check duplicate names between parameters and resources
        dup_names = set(self.parameters.keys()) & set(self.keys())

        if dup_names:
            LOG.debug("Duplicate names %s" % dup_names)
            raise StackValidationFailed(message=_("Duplicate names %s") %
                                        dup_names)

        for res in self.dependencies:
            try:
                result = res.validate()
            except exception.HeatException as ex:
                LOG.info(ex)
                raise ex
            except Exception as ex:
                LOG.exception(ex)
                raise StackValidationFailed(message=encodeutils.safe_decode(
                                            six.text_type(ex)))
            if result:
                raise StackValidationFailed(message=result)

            for val in self.outputs.values():
                snippet = val.get('Value', '')
                try:
                    function.validate(snippet)
                except Exception as ex:
                    reason = 'Output validation error: %s' % six.text_type(ex)
                    raise StackValidationFailed(message=reason)

    def requires_deferred_auth(self):
        '''
        Returns whether this stack may need to perform API requests
        during its lifecycle using the configured deferred authentication
        method.
        '''
        return any(res.requires_deferred_auth for res in self.values())

    def state_set(self, action, status, reason):
        '''Update the stack state in the database.'''
        if action not in self.ACTIONS:
            raise ValueError(_("Invalid action %s") % action)

        if status not in self.STATUSES:
            raise ValueError(_("Invalid status %s") % status)

        self.action = action
        self.status = status
        self.status_reason = reason

        if self.id is None:
            return

        stack = db_api.stack_get(self.context, self.id)
        if stack is not None:
            stack.update_and_save({'action': action,
                                   'status': status,
                                   'status_reason': reason})
            msg = _('Stack %(action)s %(status)s (%(name)s): %(reason)s')
            LOG.info(msg % {'action': action,
                            'status': status,
                            'name': self.name,
                            'reason': reason})
            notification.send(self)

    @property
    def state(self):
        '''Returns state, tuple of action, status.'''
        return (self.action, self.status)

    def timeout_secs(self):
        '''
        Return the stack action timeout in seconds.
        '''
        if self.timeout_mins is None:
            return cfg.CONF.stack_action_timeout

        return self.timeout_mins * 60

    def preview_resources(self):
        '''
        Preview the stack with all of the resources.
        '''
        return [resource.preview()
                for resource in self.resources.itervalues()]

    def create(self):
        '''
        Create the stack and all of the resources.
        '''
        def rollback():
            if not self.disable_rollback and self.state == (self.CREATE,
                                                            self.FAILED):
                self.delete(action=self.ROLLBACK)

        creator = scheduler.TaskRunner(self.stack_task,
                                       action=self.CREATE,
                                       reverse=False,
                                       post_func=rollback,
                                       error_wait_time=ERROR_WAIT_TIME)
        creator(timeout=self.timeout_secs())

    def _adopt_kwargs(self, resource):
        data = self.adopt_stack_data
        if not data or not data.get('resources'):
            return {'resource_data': None}

        return {'resource_data': data['resources'].get(resource.name)}

    @scheduler.wrappertask
    def stack_task(self, action, reverse=False, post_func=None,
                   error_wait_time=None,
                   aggregate_exceptions=False):
        '''
        A task to perform an action on the stack and all of the resources
        in forward or reverse dependency order as specified by reverse
        '''
        try:
            lifecycle_plugin_utils.do_pre_ops(self.context, self,
                                              None, action)
        except Exception as e:
            self.state_set(action, self.FAILED, e.args[0] if e.args else
                           'Failed stack pre-ops: %s' % six.text_type(e))
            if callable(post_func):
                post_func()
            return
        self.state_set(action, self.IN_PROGRESS,
                       'Stack %s started' % action)

        stack_status = self.COMPLETE
        reason = 'Stack %s completed successfully' % action

        def resource_action(r):
            # Find e.g resource.create and call it
            action_l = action.lower()
            handle = getattr(r, '%s' % action_l)

            # If a local _$action_kwargs function exists, call it to get the
            # action specific argument list, otherwise an empty arg list
            handle_kwargs = getattr(self,
                                    '_%s_kwargs' % action_l, lambda x: {})
            return handle(**handle_kwargs(r))

        action_task = scheduler.DependencyTaskGroup(
            self.dependencies,
            resource_action,
            reverse,
            error_wait_time=error_wait_time,
            aggregate_exceptions=aggregate_exceptions)

        try:
            yield action_task()
        except (exception.ResourceFailure, scheduler.ExceptionGroup) as ex:
            stack_status = self.FAILED
            reason = 'Resource %s failed: %s' % (action, six.text_type(ex))
        except scheduler.Timeout:
            stack_status = self.FAILED
            reason = '%s timed out' % action.title()

        self.state_set(action, stack_status, reason)

        if callable(post_func):
            post_func()
        lifecycle_plugin_utils.do_post_ops(self.context, self, None, action,
                                           (self.status == self.FAILED))

    def check(self):
        self.updated_time = datetime.utcnow()
        checker = scheduler.TaskRunner(self.stack_task, self.CHECK,
                                       post_func=self.supports_check_action,
                                       aggregate_exceptions=True)
        checker()

    def supports_check_action(self):
        def is_supported(stack, res):
            if hasattr(res, 'nested'):
                return res.nested().supports_check_action()
            else:
                return hasattr(res, 'handle_%s' % self.CHECK.lower())

        supported = [is_supported(self, res)
                     for res in self.resources.values()]

        if not all(supported):
            msg = ". '%s' not fully supported (see resources)" % self.CHECK
            reason = self.status_reason + msg
            self.state_set(self.CHECK, self.status, reason)

        return all(supported)

    def _backup_stack(self, create_if_missing=True):
        '''
        Get a Stack containing any in-progress resources from the previous
        stack state prior to an update.
        '''
        s = db_api.stack_get_by_name_and_owner_id(self.context,
                                                  self._backup_name(),
                                                  owner_id=self.id)
        if s is not None:
            LOG.debug('Loaded existing backup stack')
            return self.load(self.context, stack=s)
        elif create_if_missing:
            prev = type(self)(self.context, self.name, copy.deepcopy(self.t),
                              self.env, owner_id=self.id,
                              user_creds_id=self.user_creds_id)
            prev.store(backup=True)
            LOG.debug('Created new backup stack')
            return prev
        else:
            return None

    def adopt(self):
        '''
        Adopt a stack (create stack with all the existing resources).
        '''
        def rollback():
            if not self.disable_rollback and self.state == (self.ADOPT,
                                                            self.FAILED):
                # enter the same flow as abandon and just delete the stack
                for res in self.resources.values():
                    res.abandon_in_progress = True
                self.delete(action=self.ROLLBACK, abandon=True)

        creator = scheduler.TaskRunner(
            self.stack_task,
            action=self.ADOPT,
            reverse=False,
            post_func=rollback)
        creator(timeout=self.timeout_secs())

    def update(self, newstack, event=None):
        '''
        Compare the current stack with newstack,
        and where necessary create/update/delete the resources until
        this stack aligns with newstack.

        Note update of existing stack resources depends on update
        being implemented in the underlying resource types

        Update will fail if it exceeds the specified timeout. The default is
        60 minutes, set in the constructor
        '''
        self.updated_time = datetime.utcnow()
        updater = scheduler.TaskRunner(self.update_task, newstack,
                                       event=event)
        updater()

    @scheduler.wrappertask
    def update_task(self, newstack, action=UPDATE, event=None):
        if action not in (self.UPDATE, self.ROLLBACK):
            LOG.error(_("Unexpected action %s passed to update!") % action)
            self.state_set(self.UPDATE, self.FAILED,
                           "Invalid action %s" % action)
            return

        try:
            lifecycle_plugin_utils.do_pre_ops(self.context, self,
                                              newstack, action)
        except Exception as e:
            self.state_set(action, self.FAILED, e.args[0] if e.args else
                           'Failed stack pre-ops: %s' % six.text_type(e))
            return
        if self.status == self.IN_PROGRESS:
            if action == self.ROLLBACK:
                LOG.debug("Starting update rollback for %s" % self.name)
            else:
                self.state_set(action, self.FAILED,
                               'State invalid for %s' % action)
                return

        self.state_set(action, self.IN_PROGRESS,
                       'Stack %s started' % action)

        if action == self.UPDATE:
            # Oldstack is useless when the action is not UPDATE , so we don't
            # need to build it, this can avoid some unexpected errors.
            oldstack = Stack(self.context, self.name, copy.deepcopy(self.t),
                             self.env)
        backup_stack = self._backup_stack()
        existing_params = environment.Environment({env_fmt.PARAMETERS:
                                                  self.env.params})
        try:
            update_task = update.StackUpdate(self, newstack, backup_stack,
                                             rollback=action == self.ROLLBACK,
                                             error_wait_time=ERROR_WAIT_TIME)
            updater = scheduler.TaskRunner(update_task)

            self.env = newstack.env
            self.parameters = newstack.parameters
            self.t.files = newstack.t.files
            self.disable_rollback = newstack.disable_rollback
            self.timeout_mins = newstack.timeout_mins
            self._set_param_stackid()

            try:
                updater.start(timeout=self.timeout_secs())
                yield
                while not updater.step():
                    if event is None or not event.ready():
                        yield
                    else:
                        message = event.wait()
                        if message == rpc_api.THREAD_CANCEL:
                            raise ForcedCancel()
            finally:
                self.reset_dependencies()

            if action == self.UPDATE:
                reason = 'Stack successfully updated'
            else:
                reason = 'Stack rollback completed'
            stack_status = self.COMPLETE

        except scheduler.Timeout:
            stack_status = self.FAILED
            reason = 'Timed out'
        except ForcedCancel as e:
            reason = six.text_type(e)

            stack_status = self.FAILED
            if action == self.UPDATE:
                update_task.updater.cancel_all()
                yield self.update_task(oldstack, action=self.ROLLBACK)
                return

        except exception.ResourceFailure as e:
            reason = six.text_type(e)

            stack_status = self.FAILED
            if action == self.UPDATE:
                # If rollback is enabled, we do another update, with the
                # existing template, so we roll back to the original state
                if not self.disable_rollback:
                    yield self.update_task(oldstack, action=self.ROLLBACK)
                    return
        else:
            LOG.debug('Deleting backup stack')
            backup_stack.delete(backup=True)

            # flip the template to the newstack values
            self.t = newstack.t
            template_outputs = self.t[self.t.OUTPUTS]
            self.outputs = self.resolve_static_data(template_outputs)

        # Don't use state_set to do only one update query and avoid race
        # condition with the COMPLETE status
        self.action = action
        self.status = stack_status
        self.status_reason = reason

        if self.status == self.FAILED:
            # Since template was incrementally updated based on existing and
            # new stack resources, we should have user params of both.
            existing_params.load(newstack.env.user_env_as_dict())
            self.env = existing_params

        self.store()
        lifecycle_plugin_utils.do_post_ops(self.context, self,
                                           newstack, action,
                                           (self.status == self.FAILED))

        notification.send(self)

    def delete(self, action=DELETE, backup=False, abandon=False):
        '''
        Delete all of the resources, and then the stack itself.
        The action parameter is used to differentiate between a user
        initiated delete and an automatic stack rollback after a failed
        create, which amount to the same thing, but the states are recorded
        differently.

        Note abandon is a delete where all resources have been set to a
        RETAIN deletion policy, but we also don't want to delete anything
        required for those resources, e.g the stack_user_project.
        '''
        if action not in (self.DELETE, self.ROLLBACK):
            LOG.error(_("Unexpected action %s passed to delete!") % action)
            self.state_set(self.DELETE, self.FAILED,
                           "Invalid action %s" % action)
            return

        stack_status = self.COMPLETE
        reason = 'Stack %s completed successfully' % action
        self.state_set(action, self.IN_PROGRESS, 'Stack %s started' %
                       action)

        backup_stack = self._backup_stack(False)
        if backup_stack:
            def failed(child):
                return (child.action == child.CREATE and
                        child.status in (child.FAILED, child.IN_PROGRESS))

            for key, backup_resource in backup_stack.resources.items():
                # If UpdateReplace is failed, we must restore backup_resource
                # to existing_stack in case of it may have dependencies in
                # these stacks. current_resource is the resource that just
                # created and failed, so put into the backup_stack to delete
                # anyway.
                backup_resource_id = backup_resource.resource_id
                current_resource = self.resources.get(key)
                if (backup_resource_id is not None and
                        current_resource is not None):
                    current_resource_id = current_resource.resource_id
                    if (any(failed(child) for child in
                            self.dependencies[current_resource]) or
                            current_resource.status in
                            (current_resource.FAILED,
                             current_resource.IN_PROGRESS)):
                        # If child resource failed to update, current_resource
                        # should be replaced to resolve dependencies. But this
                        # is not fundamental solution. If there are update
                        # failer and success resources in the children, cannot
                        # delete the stack.
                        # Stack class owns dependencies as set of resource's
                        # objects, so we switch members of the resource that is
                        # needed to delete it.
                        self.resources[key].resource_id = backup_resource_id
                        self.resources[
                            key].properties = backup_resource.properties
                        backup_stack.resources[
                            key].resource_id = current_resource_id
                        backup_stack.resources[
                            key].properties = current_resource.properties

            backup_stack.delete(backup=True)
            if backup_stack.status != backup_stack.COMPLETE:
                errs = backup_stack.status_reason
                failure = 'Error deleting backup resources: %s' % errs
                self.state_set(action, self.FAILED,
                               'Failed to %s : %s' % (action, failure))
                return

        snapshots = db_api.snapshot_get_all(self.context, self.id)
        for snapshot in snapshots:
            self.delete_snapshot(snapshot)

        if not backup:
            try:
                lifecycle_plugin_utils.do_pre_ops(self.context, self,
                                                  None, action)
            except Exception as e:
                self.state_set(action, self.FAILED,
                               e.args[0] if e.args else
                               'Failed stack pre-ops: %s' % six.text_type(e))
                return
        action_task = scheduler.DependencyTaskGroup(self.dependencies,
                                                    resource.Resource.destroy,
                                                    reverse=True)
        try:
            scheduler.TaskRunner(action_task)(timeout=self.timeout_secs())
        except exception.ResourceFailure as ex:
            stack_status = self.FAILED
            reason = 'Resource %s failed: %s' % (action, six.text_type(ex))
        except scheduler.Timeout:
            stack_status = self.FAILED
            reason = '%s timed out' % action.title()

        # If the stack delete succeeded, this is not a backup stack and it's
        # not a nested stack, we should delete the credentials
        if stack_status != self.FAILED and not backup and not self.owner_id:
            # Cleanup stored user_creds so they aren't accessible via
            # the soft-deleted stack which remains in the DB
            if self.user_creds_id:
                user_creds = db_api.user_creds_get(self.user_creds_id)
                # If we created a trust, delete it
                if user_creds is not None:
                    trust_id = user_creds.get('trust_id')
                    if trust_id:
                        try:
                            # If the trustor doesn't match the context user the
                            # we have to use the stored context to cleanup the
                            # trust, as although the user evidently has
                            # permission to delete the stack, they don't have
                            # rights to delete the trust unless an admin
                            trustor_id = user_creds.get('trustor_user_id')
                            if self.context.user_id != trustor_id:
                                LOG.debug('Context user_id doesn\'t match '
                                          'trustor, using stored context')
                                sc = self.stored_context()
                                sc.clients.client('keystone').delete_trust(
                                    trust_id)
                            else:
                                self.clients.client('keystone').delete_trust(
                                    trust_id)
                        except Exception as ex:
                            LOG.exception(ex)
                            stack_status = self.FAILED
                            reason = ("Error deleting trust: %s" %
                                      six.text_type(ex))

                # Delete the stored credentials
                try:
                    db_api.user_creds_delete(self.context, self.user_creds_id)
                except exception.NotFound:
                    LOG.info(_("Tried to delete user_creds that do not exist "
                               "(stack=%(stack)s user_creds_id=%(uc)s)") %
                             {'stack': self.id, 'uc': self.user_creds_id})

                try:
                    self.user_creds_id = None
                    self.store()
                except exception.NotFound:
                    LOG.info(_("Tried to store a stack that does not exist "
                               "%s ") % self.id)

            # If the stack has a domain project, delete it
            if self.stack_user_project_id and not abandon:
                try:
                    keystone = self.clients.client('keystone')
                    keystone.delete_stack_domain_project(
                        project_id=self.stack_user_project_id)
                except Exception as ex:
                    LOG.exception(ex)
                    stack_status = self.FAILED
                    reason = "Error deleting project: %s" % six.text_type(ex)

        try:
            self.state_set(action, stack_status, reason)
        except exception.NotFound:
            LOG.info(_("Tried to delete stack that does not exist "
                       "%s ") % self.id)

        if not backup:
            lifecycle_plugin_utils.do_post_ops(self.context, self,
                                               None, action,
                                               (self.status == self.FAILED))
        if stack_status != self.FAILED:
            # delete the stack
            try:
                db_api.stack_delete(self.context, self.id)
            except exception.NotFound:
                LOG.info(_("Tried to delete stack that does not exist "
                           "%s ") % self.id)
            self.id = None

    def suspend(self):
        '''
        Suspend the stack, which invokes handle_suspend for all stack resources
        waits for all resources to become SUSPEND_COMPLETE then declares the
        stack SUSPEND_COMPLETE.
        Note the default implementation for all resources is to do nothing
        other than move to SUSPEND_COMPLETE, so the resources must implement
        handle_suspend for this to have any effect.
        '''
        # No need to suspend if the stack has been suspended
        if self.state == (self.SUSPEND, self.COMPLETE):
            LOG.info(_('%s is already suspended') % str(self))
            return

        sus_task = scheduler.TaskRunner(self.stack_task,
                                        action=self.SUSPEND,
                                        reverse=True)
        sus_task(timeout=self.timeout_secs())

    def resume(self):
        '''
        Resume the stack, which invokes handle_resume for all stack resources
        waits for all resources to become RESUME_COMPLETE then declares the
        stack RESUME_COMPLETE.
        Note the default implementation for all resources is to do nothing
        other than move to RESUME_COMPLETE, so the resources must implement
        handle_resume for this to have any effect.
        '''
        # No need to resume if the stack has been resumed
        if self.state == (self.RESUME, self.COMPLETE):
            LOG.info(_('%s is already resumed') % str(self))
            return

        sus_task = scheduler.TaskRunner(self.stack_task,
                                        action=self.RESUME,
                                        reverse=False)
        sus_task(timeout=self.timeout_secs())

    def snapshot(self):
        '''Snapshot the stack, invoking handle_snapshot on all resources.'''
        sus_task = scheduler.TaskRunner(self.stack_task,
                                        action=self.SNAPSHOT,
                                        reverse=False)
        sus_task(timeout=self.timeout_secs())

    def delete_snapshot(self, snapshot):
        '''Remove a snapshot from the backends.'''
        for name, rsrc in self.resources.iteritems():
            snapshot_data = snapshot.data
            if snapshot_data:
                data = snapshot.data['resources'].get(name)
                scheduler.TaskRunner(rsrc.delete_snapshot, data)()

    def output(self, key):
        '''
        Get the value of the specified stack output.
        '''
        value = self.outputs[key].get('Value', '')
        try:
            return function.resolve(value)
        except Exception as ex:
            self.outputs[key]['error_msg'] = six.text_type(ex)
            return None

    def restart_resource(self, resource_name):
        '''
        stop resource_name and all that depend on it
        start resource_name and all that depend on it
        '''
        deps = self.dependencies[self[resource_name]]
        failed = False

        for res in reversed(deps):
            try:
                scheduler.TaskRunner(res.destroy)()
            except exception.ResourceFailure as ex:
                failed = True
                LOG.error(_('Resource %(name)s delete failed: %(ex)s') %
                          {'name': res.name, 'ex': ex})

        for res in deps:
            if not failed:
                try:
                    res.state_reset()
                    scheduler.TaskRunner(res.create)()
                except exception.ResourceFailure as ex:
                    LOG.exception(_('Resource %(name)s create failed: %(ex)s')
                                  % {'name': res.name, 'ex': ex})
                    failed = True
            else:
                res.state_set(res.CREATE, res.FAILED,
                              'Resource restart aborted')
        # TODO(asalkeld) if any of this fails we Should
        # restart the whole stack

    def get_availability_zones(self):
        nova = self.clients.client('nova')
        if self._zones is None:
            self._zones = [
                zone.zoneName for zone in
                nova.availability_zones.list(detailed=False)]
        return self._zones

    def set_stack_user_project_id(self, project_id):
        self.stack_user_project_id = project_id
        self.store()

    def create_stack_user_project_id(self):
        project_id = self.clients.client(
            'keystone').create_stack_domain_project(self.id)
        self.set_stack_user_project_id(project_id)

    def prepare_abandon(self):
        return {
            'name': self.name,
            'id': self.id,
            'action': self.action,
            'environment': self.env.user_env_as_dict(),
            'status': self.status,
            'template': self.t.t,
            'resources': dict((res.name, res.prepare_abandon())
                              for res in self.resources.values()),
            'project_id': self.tenant_id,
            'stack_user_project_id': self.stack_user_project_id
        }

    def resolve_static_data(self, snippet):
        return self.t.parse(self, snippet)

    def resolve_runtime_data(self, snippet):
        """DEPRECATED. Use heat.engine.function.resolve() instead."""
        warnings.warn('Stack.resolve_runtime_data() is deprecated. '
                      'Use heat.engine.function.resolve() instead',
                      DeprecationWarning)
        return function.resolve(snippet)

    def reset_resource_attributes(self):
        # nothing is cached if no resources exist
        if not self._resources:
            return
        # a change in some resource may have side-effects in the attributes
        # of other resources, so ensure that attributes are re-calculated
        for res in self.resources.itervalues():
            res.attributes.reset_resolved_values()
