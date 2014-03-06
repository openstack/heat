
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
import six

from oslo.config import cfg

from heat.engine import environment
from heat.common import exception
from heat.engine import dependencies
from heat.common import identifier
from heat.engine import function
from heat.engine import resource
from heat.engine import resources
from heat.engine import scheduler
from heat.engine import update
from heat.engine.notification import stack as notification
from heat.engine.parameter_groups import ParameterGroups
from heat.engine.template import Template
from heat.engine.clients import Clients
from heat.db import api as db_api

from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _
from heat.openstack.common import strutils

from heat.common.exception import StackValidationFailed

logger = logging.getLogger(__name__)


class Stack(collections.Mapping):

    ACTIONS = (CREATE, DELETE, UPDATE, ROLLBACK, SUSPEND, RESUME, ADOPT
               ) = ('CREATE', 'DELETE', 'UPDATE', 'ROLLBACK', 'SUSPEND',
                    'RESUME', 'ADOPT')

    STATUSES = (IN_PROGRESS, FAILED, COMPLETE
                ) = ('IN_PROGRESS', 'FAILED', 'COMPLETE')

    _zones = None

    def __init__(self, context, stack_name, tmpl, env=None,
                 stack_id=None, action=None, status=None,
                 status_reason='', timeout_mins=60, resolve_data=True,
                 disable_rollback=True, parent_resource=None, owner_id=None,
                 adopt_stack_data=None, stack_user_project_id=None,
                 created_time=None, updated_time=None):
        '''
        Initialise from a context, name, Template object and (optionally)
        Environment object. The database ID may also be initialised, if the
        stack is already in the database.
        '''

        if owner_id is None:
            if re.match("[a-zA-Z][a-zA-Z0-9_.-]*$", stack_name) is None:
                raise ValueError(_('Invalid stack name %s'
                                   ' must contain only alphanumeric or '
                                   '\"_-.\" characters, must start with alpha'
                                   ) % stack_name)

        self.id = stack_id
        self.owner_id = owner_id
        self.context = context
        self.clients = Clients(context)
        self.t = tmpl
        self.name = stack_name
        self.action = action
        self.status = status
        self.status_reason = status_reason
        self.timeout_mins = timeout_mins
        self.disable_rollback = disable_rollback
        self.parent_resource = parent_resource
        self._resources = None
        self._dependencies = None
        self._access_allowed_handlers = {}
        self.adopt_stack_data = adopt_stack_data
        self.stack_user_project_id = stack_user_project_id
        self.created_time = created_time
        self.updated_time = updated_time

        resources.initialise()

        self.env = env or environment.Environment({})
        self.parameters = self.t.parameters(self.identifier(),
                                            user_params=self.env.params,
                                            context=context)

        self._set_param_stackid()

        if resolve_data:
            self.outputs = self.resolve_static_data(self.t[self.t.OUTPUTS])
        else:
            self.outputs = {}

    @property
    def resources(self):
        if self._resources is None:
            template_resources = self.t[self.t.RESOURCES]
            self._resources = dict((name, resource.Resource(name, data, self))
                                   for (name, data) in
                                   template_resources.items())
        return self._resources

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
            logger.warning(_("Unable to set parameters StackId identifier"))

    @staticmethod
    def _get_dependencies(resources):
        '''Return the dependency graph for a list of resources.'''
        deps = dependencies.Dependencies()
        for resource in resources:
            resource.add_dependencies(deps)

        return deps

    @classmethod
    def load(cls, context, stack_id=None, stack=None, resolve_data=True,
             parent_resource=None, show_deleted=True):
        '''Retrieve a Stack from the database.'''
        if stack is None:
            stack = db_api.stack_get(context, stack_id,
                                     show_deleted=show_deleted)
        if stack is None:
            message = _('No stack exists with id "%s"') % str(stack_id)
            raise exception.NotFound(message)

        template = Template.load(context, stack.raw_template_id)
        env = environment.Environment(stack.parameters)
        stack = cls(context, stack.name, template, env,
                    stack.id, stack.action, stack.status, stack.status_reason,
                    stack.timeout, resolve_data, stack.disable_rollback,
                    parent_resource, owner_id=stack.owner_id,
                    stack_user_project_id=stack.stack_user_project_id,
                    created_time=stack.created_at,
                    updated_time=stack.updated_at)

        return stack

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
            'username': self.context.username,
            'tenant': self.context.tenant_id,
            'action': self.action,
            'status': self.status,
            'status_reason': self.status_reason,
            'timeout': self.timeout_mins,
            'disable_rollback': self.disable_rollback,
            'stack_user_project_id': self.stack_user_project_id,
            'updated_at': self.updated_time,
        }
        if self.id:
            db_api.stack_update(self.context, self.id, s)
        else:
            # Create a context containing a trust_id and trustor_user_id
            # if trusts are enabled
            if cfg.CONF.deferred_auth_method == 'trusts':
                trust_context = self.clients.keystone().create_trust_context()
                new_creds = db_api.user_creds_create(trust_context)
            else:
                new_creds = db_api.user_creds_create(self.context)
            s['user_creds_id'] = new_creds.id

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
        return identifier.HeatIdentifier(self.context.tenant_id,
                                         self.name, self.id)

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

    def __setitem__(self, key, resource):
        '''Set the resource with the specified name to a specific value.'''
        resource.stack = self
        resource.reparse()
        self.resources[key] = resource

    def __delitem__(self, key):
        '''Remove the resource with the specified name.'''
        del self.resources[key]

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

        # Validate Parameter Groups
        parameter_groups = ParameterGroups(self.t)
        parameter_groups.validate()

        # Check duplicate names between parameters and resources
        dup_names = set(self.parameters.keys()) & set(self.keys())

        if dup_names:
            logger.debug(_("Duplicate names %s") % dup_names)
            raise StackValidationFailed(message=_("Duplicate names %s") %
                                        dup_names)

        for res in self.dependencies:
            try:
                result = res.validate()
            except exception.Error as ex:
                logger.exception(ex)
                raise ex
            except Exception as ex:
                logger.exception(ex)
                raise StackValidationFailed(message=strutils.safe_decode(
                                            six.text_type(ex)))
            if result:
                raise StackValidationFailed(message=result)

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
            notification.send(self)

    @property
    def state(self):
        '''Returns state, tuple of action, status.'''
        return (self.action, self.status)

    def timeout_secs(self):
        '''
        Return the stack creation timeout in seconds, or None if no timeout
        should be used.
        '''
        if self.timeout_mins is None:
            return None

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
                                       post_func=rollback)
        creator(timeout=self.timeout_secs())

    def _adopt_kwargs(self, resource):
        data = self.adopt_stack_data
        if not data or not data.get('resources'):
            return {'resource_data': None}

        return {'resource_data': data['resources'].get(resource.name)}

    @scheduler.wrappertask
    def stack_task(self, action, reverse=False, post_func=None):
        '''
        A task to perform an action on the stack and all of the resources
        in forward or reverse dependency order as specfifed by reverse
        '''
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

        action_task = scheduler.DependencyTaskGroup(self.dependencies,
                                                    resource_action,
                                                    reverse)

        try:
            yield action_task()
        except exception.ResourceFailure as ex:
            stack_status = self.FAILED
            reason = 'Resource %s failed: %s' % (action, str(ex))
        except scheduler.Timeout:
            stack_status = self.FAILED
            reason = '%s timed out' % action.title()

        self.state_set(action, stack_status, reason)

        if callable(post_func):
            post_func()

    def _backup_stack(self, create_if_missing=True):
        '''
        Get a Stack containing any in-progress resources from the previous
        stack state prior to an update.
        '''
        s = db_api.stack_get_by_name_and_owner_id(self.context,
                                                  self._backup_name(),
                                                  owner_id=self.id)
        if s is not None:
            logger.debug(_('Loaded existing backup stack'))
            return self.load(self.context, stack=s)
        elif create_if_missing:
            templ = Template.load(self.context, self.t.id)
            templ.files = copy.deepcopy(self.t.files)
            prev = type(self)(self.context, self.name, templ, self.env,
                              owner_id=self.id)
            prev.store(backup=True)
            logger.debug(_('Created new backup stack'))
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
                self.delete(action=self.ROLLBACK)

        creator = scheduler.TaskRunner(
            self.stack_task,
            action=self.ADOPT,
            reverse=False,
            post_func=rollback)
        creator(timeout=self.timeout_secs())

    def update(self, newstack):
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
        updater = scheduler.TaskRunner(self.update_task, newstack)
        updater()

    @scheduler.wrappertask
    def update_task(self, newstack, action=UPDATE):
        if action not in (self.UPDATE, self.ROLLBACK):
            logger.error(_("Unexpected action %s passed to update!") %
                         action)
            self.state_set(self.UPDATE, self.FAILED,
                           "Invalid action %s" % action)
            return

        if self.status != self.COMPLETE:
            if (action == self.ROLLBACK and
                    self.state == (self.UPDATE, self.IN_PROGRESS)):
                logger.debug(_("Starting update rollback for %s") % self.name)
            else:
                self.state_set(action, self.FAILED,
                               'State invalid for %s' % action)
                return

        self.state_set(self.UPDATE, self.IN_PROGRESS,
                       'Stack %s started' % action)

        oldstack = Stack(self.context, self.name, self.t, self.env)
        backup_stack = self._backup_stack()
        try:
            update_task = update.StackUpdate(self, newstack, backup_stack,
                                             rollback=action == self.ROLLBACK)
            updater = scheduler.TaskRunner(update_task)

            self.env = newstack.env
            self.parameters = newstack.parameters
            self.t.files = newstack.t.files
            self._set_param_stackid()

            try:
                updater.start(timeout=self.timeout_secs())
                yield
                while not updater.step():
                    yield
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
        except exception.ResourceFailure as e:
            reason = str(e)

            stack_status = self.FAILED
            if action == self.UPDATE:
                # If rollback is enabled, we do another update, with the
                # existing template, so we roll back to the original state
                if not self.disable_rollback:
                    yield self.update_task(oldstack, action=self.ROLLBACK)
                    return
        else:
            logger.debug(_('Deleting backup stack'))
            backup_stack.delete(backup=True)

        self.state_set(action, stack_status, reason)

        # flip the template to the newstack values
        # Note we do this on success and failure, so the current
        # stack resources are stored, even if one is in a failed
        # state (otherwise we won't remove them on delete)
        self.t = newstack.t
        template_outputs = self.t[self.t.OUTPUTS]
        self.outputs = self.resolve_static_data(template_outputs)
        self.store()

    def delete(self, action=DELETE, backup=False):
        '''
        Delete all of the resources, and then the stack itself.
        The action parameter is used to differentiate between a user
        initiated delete and an automatic stack rollback after a failed
        create, which amount to the same thing, but the states are recorded
        differently.
        '''
        if action not in (self.DELETE, self.ROLLBACK):
            logger.error(_("Unexpected action %s passed to delete!") % action)
            self.state_set(self.DELETE, self.FAILED,
                           "Invalid action %s" % action)
            return

        stack_status = self.COMPLETE
        reason = 'Stack %s completed successfully' % action
        self.state_set(action, self.IN_PROGRESS, 'Stack %s started' %
                       action)

        backup_stack = self._backup_stack(False)
        if backup_stack is not None:
            backup_stack.delete(backup=True)
            if backup_stack.status != backup_stack.COMPLETE:
                errs = backup_stack.status_reason
                failure = 'Error deleting backup resources: %s' % errs
                self.state_set(action, self.FAILED,
                               'Failed to %s : %s' % (action, failure))
                return

        action_task = scheduler.DependencyTaskGroup(self.dependencies,
                                                    resource.Resource.destroy,
                                                    reverse=True)
        try:
            scheduler.TaskRunner(action_task)(timeout=self.timeout_secs())
        except exception.ResourceFailure as ex:
            stack_status = self.FAILED
            reason = 'Resource %s failed: %s' % (action, str(ex))
        except scheduler.Timeout:
            stack_status = self.FAILED
            reason = '%s timed out' % action.title()

        if stack_status != self.FAILED and not backup:
            # If we created a trust, delete it
            stack = db_api.stack_get(self.context, self.id)
            user_creds = db_api.user_creds_get(stack.user_creds_id)
            trust_id = user_creds.get('trust_id')
            if trust_id:
                try:
                    self.clients.keystone().delete_trust(trust_id)
                except Exception as ex:
                    logger.exception(ex)
                    stack_status = self.FAILED
                    reason = "Error deleting trust: %s" % str(ex)

            # If the stack has a domain project, delete it
            if self.stack_user_project_id:
                try:
                    self.clients.keystone().delete_stack_domain_project(
                        project_id=self.stack_user_project_id)
                except Exception as ex:
                    logger.exception(ex)
                    stack_status = self.FAILED
                    reason = "Error deleting project: %s" % str(ex)

        self.state_set(action, stack_status, reason)

        if stack_status != self.FAILED:
            # delete the stack
            db_api.stack_delete(self.context, self.id)
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
        sus_task = scheduler.TaskRunner(self.stack_task,
                                        action=self.RESUME,
                                        reverse=False)
        sus_task(timeout=self.timeout_secs())

    def output(self, key):
        '''
        Get the value of the specified stack output.
        '''
        value = self.outputs[key].get('Value', '')
        return self.resolve_runtime_data(value)

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
                logger.error(_('delete: %s') % str(ex))

        for res in deps:
            if not failed:
                try:
                    res.state_reset()
                    scheduler.TaskRunner(res.create)()
                except exception.ResourceFailure as ex:
                    logger.exception(_('create'))
                    failed = True
            else:
                res.state_set(res.CREATE, res.FAILED,
                              'Resource restart aborted')
        # TODO(asalkeld) if any of this fails we Should
        # restart the whole stack

    def get_availability_zones(self):
        if self._zones is None:
            self._zones = [
                zone.zoneName for zone in
                self.clients.nova().availability_zones.list(detailed=False)]
        return self._zones

    def set_deletion_policy(self, policy):
        for res in self.resources.values():
            res.set_deletion_policy(policy)

    def set_stack_user_project_id(self, project_id):
        self.stack_user_project_id = project_id
        self.store()

    def get_abandon_data(self):
        return {
            'name': self.name,
            'id': self.id,
            'action': self.action,
            'status': self.status,
            'template': self.t.t,
            'resources': dict((res.name, res.get_abandon_data())
                              for res in self.resources.values())
        }

    def resolve_static_data(self, snippet):
        return self.t.parse(self, snippet)

    def resolve_runtime_data(self, snippet):
        return function.resolve(snippet)
