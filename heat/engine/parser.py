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

import eventlet
import functools

from heat.common import exception
from heat.engine import dependencies
from heat.engine import identifier
from heat.engine import resources
from heat.engine import template
from heat.engine import timestamp
from heat.engine.parameters import Parameters
from heat.engine.template import Template
from heat.engine.clients import Clients
from heat.db import api as db_api

from heat.openstack.common import log as logging

logger = logging.getLogger('heat.engine.parser')

(PARAM_STACK_NAME, PARAM_REGION) = ('AWS::StackName', 'AWS::Region')


class Stack(object):
    CREATE_IN_PROGRESS = 'CREATE_IN_PROGRESS'
    CREATE_FAILED = 'CREATE_FAILED'
    CREATE_COMPLETE = 'CREATE_COMPLETE'

    DELETE_IN_PROGRESS = 'DELETE_IN_PROGRESS'
    DELETE_FAILED = 'DELETE_FAILED'
    DELETE_COMPLETE = 'DELETE_COMPLETE'

    UPDATE_IN_PROGRESS = 'UPDATE_IN_PROGRESS'
    UPDATE_COMPLETE = 'UPDATE_COMPLETE'
    UPDATE_FAILED = 'UPDATE_FAILED'

    created_time = timestamp.Timestamp(db_api.stack_get, 'created_at')
    updated_time = timestamp.Timestamp(db_api.stack_get, 'updated_at')

    def __init__(self, context, stack_name, tmpl, parameters=None,
                 stack_id=None, state=None, state_description='',
                 timeout_mins=60, resolve_data=True):
        '''
        Initialise from a context, name, Template object and (optionally)
        Parameters object. The database ID may also be initialised, if the
        stack is already in the database.
        '''
        self.id = stack_id
        self.context = context
        self.clients = Clients(context)
        self.t = tmpl
        self.name = stack_name
        self.state = state
        self.state_description = state_description
        self.timeout_mins = timeout_mins

        if parameters is None:
            parameters = Parameters(self.name, self.t)
        self.parameters = parameters

        if resolve_data:
            self.outputs = self.resolve_static_data(self.t[template.OUTPUTS])
        else:
            self.outputs = {}

        template_resources = self.t[template.RESOURCES]
        self.resources = dict((name,
                               resources.Resource(name, data, self))
                              for (name, data) in template_resources.items())

        self.dependencies = self._get_dependencies(self.resources.itervalues())

    @staticmethod
    def _get_dependencies(resources):
        '''Return the dependency graph for a list of resources'''
        deps = dependencies.Dependencies()
        for resource in resources:
            resource.add_dependencies(deps)

        return deps

    @classmethod
    def load(cls, context, stack_id=None, stack=None, resolve_data=True):
        '''Retrieve a Stack from the database'''
        if stack is None:
            stack = db_api.stack_get(context, stack_id)
        if stack is None:
            message = 'No stack exists with id "%s"' % str(stack_id)
            raise exception.NotFound(message)

        template = Template.load(context, stack.raw_template_id)
        params = Parameters(stack.name, template, stack.parameters)
        stack = cls(context, stack.name, template, params,
                    stack.id, stack.status, stack.status_reason, stack.timeout,
                    resolve_data)

        return stack

    def store(self, owner=None):
        '''
        Store the stack in the database and return its ID
        If self.id is set, we update the existing stack
        '''
        new_creds = db_api.user_creds_create(self.context)

        s = {
            'name': self.name,
            'raw_template_id': self.t.store(self.context),
            'parameters': self.parameters.user_parameters(),
            'owner_id': owner and owner.id,
            'user_creds_id': new_creds.id,
            'username': self.context.username,
            'tenant': self.context.tenant_id,
            'status': self.state,
            'status_reason': self.state_description,
            'timeout': self.timeout_mins,
        }
        if self.id:
            db_api.stack_update(self.context, self.id, s)
        else:
            new_s = db_api.stack_create(self.context, s)
            self.id = new_s.id

        return self.id

    def identifier(self):
        '''
        Return an identifier for this stack.
        '''
        return identifier.HeatIdentifier(self.context.tenant_id,
                                         self.name, self.id)

    def __iter__(self):
        '''
        Return an iterator over this template's resources in the order that
        they should be started.
        '''
        return iter(self.dependencies)

    def __reversed__(self):
        '''
        Return an iterator over this template's resources in the order that
        they should be stopped.
        '''
        return reversed(self.dependencies)

    def __len__(self):
        '''Return the number of resources'''
        return len(self.resources)

    def __getitem__(self, key):
        '''Get the resource with the specified name.'''
        return self.resources[key]

    def __setitem__(self, key, value):
        '''Set the resource with the specified name to a specific value'''
        self.resources[key] = value

    def __contains__(self, key):
        '''Determine whether the stack contains the specified resource'''
        return key in self.resources

    def keys(self):
        '''Return a list of resource keys for the stack'''
        return self.resources.keys()

    def __str__(self):
        '''Return a human-readable string representation of the stack'''
        return 'Stack "%s"' % self.name

    def validate(self):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/\
        APIReference/API_ValidateTemplate.html
        '''
        # TODO(sdake) Should return line number of invalid reference

        for res in self:
            try:
                result = res.validate()
            except Exception as ex:
                logger.exception('validate')
                result = str(ex)

            if result:
                return 'Malformed Query Response %s' % result

    def state_set(self, new_status, reason):
        '''Update the stack state in the database'''
        self.state = new_status
        self.state_description = reason

        if self.id is None:
            return

        stack = db_api.stack_get(self.context, self.id)
        stack.update_and_save({'status': new_status,
                               'status_reason': reason})

    def create(self):
        '''
        Create the stack and all of the resources.

        Creation will fail if it exceeds the specified timeout. The default is
        60 minutes, set in the constructor
        '''
        self.state_set(self.CREATE_IN_PROGRESS, 'Stack creation started')

        stack_status = self.CREATE_COMPLETE
        reason = 'Stack successfully created'
        res = None

        with eventlet.Timeout(self.timeout_mins * 60) as tmo:
            try:
                for res in self:
                    if stack_status != self.CREATE_FAILED:
                        result = res.create()
                        if result:
                            stack_status = self.CREATE_FAILED
                            reason = 'Resource %s failed with: %s' % (str(res),
                                                                      result)

                    else:
                        res.state_set(res.CREATE_FAILED,
                                      'Stack creation aborted')

            except eventlet.Timeout as t:
                if t is tmo:
                    stack_status = self.CREATE_FAILED
                    reason = 'Timed out waiting for %s' % str(res)
                else:
                    # not my timeout
                    raise

        self.state_set(stack_status, reason)

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
        if self.state not in (self.CREATE_COMPLETE, self.UPDATE_COMPLETE):
            self.state_set(self.UPDATE_FAILED, 'State invalid for update')
            return
        else:
            self.state_set(self.UPDATE_IN_PROGRESS, 'Stack update started')

        # Now make the resources match the new stack definition
        failures = []
        with eventlet.Timeout(self.timeout_mins * 60) as tmo:
            try:
                # First delete any resources which are not in newstack
                for res in reversed(self):
                    if not res.name in newstack.keys():
                        logger.debug("resource %s not found in updated stack"
                                      % res.name + " definition, deleting")
                        result = res.destroy()
                        if result:
                            failures.append('Resource %s delete failed'
                                            % res.name)
                        else:
                            del self.resources[res.name]

                # Then create any which are defined in newstack but not self
                for res in newstack:
                    if not res.name in self.keys():
                        logger.debug("resource %s not found in current stack"
                                      % res.name + " definition, adding")
                        res.stack = self
                        self[res.name] = res
                        result = self[res.name].create()
                        if result:
                            failures.append('Resource %s create failed'
                                            % res.name)

                # Now (the hard part :) update existing resources
                # The Resource base class allows equality-test of resources,
                # based on the parsed template snippet for the resource.
                # If this  test fails, we call the underlying resource.update
                #
                # FIXME : Implement proper update logic for the resources
                # AWS define three update strategies, applied depending
                # on the resource and what is being updated within a
                # resource :
                # - Update with no interruption
                # - Update with some interruption
                # - Update requires replacement
                #
                # Currently all resource have a default handle_update method
                # which returns "requires replacement" (res.UPDATE_REPLACE)
                for res in newstack:
                    if self[res.name] != res:
                        # Can fail if underlying resource class does not
                        # implement update logic or update requires replacement
                        retval = self[res.name].update(res.parsed_template())
                        if retval == self[res.name].UPDATE_REPLACE:
                            logger.info("Resource %s for stack %s" %
                                        (res.name, self.name) +
                                        " update requires replacement")
                            # Resource requires replacement for update
                            result = self[res.name].destroy()
                            if result:
                                failures.append('Resource %s delete failed'
                                                % res.name)
                            else:
                                res.stack = self
                                self[res.name] = res
                                result = self[res.name].create()
                                if result:
                                    failures.append('Resource %s create failed'
                                                    % res.name)
                        else:
                            logger.warning("Cannot update resource %s," %
                                            res.name + " reason %s" % retval)
                            failures.append('Resource %s update failed'
                                            % res.name)

                # Set stack status values
                if not failures:
                    # flip the template & parameters to the newstack values
                    self.t = newstack.t
                    self.parameters = newstack.parameters
                    template_outputs = self.t[template.OUTPUTS]
                    self.outputs = self.resolve_static_data(template_outputs)
                    self.dependencies = self._get_dependencies(
                        self.resources.itervalues())
                    self.store()

                    stack_status = self.UPDATE_COMPLETE
                    reason = 'Stack successfully updated'
                else:
                    stack_status = self.UPDATE_FAILED
                    reason = ",".join(failures)

            except eventlet.Timeout as t:
                if t is tmo:
                    stack_status = self.UPDATE_FAILED
                    reason = 'Timed out waiting for %s' % str(res)
                else:
                    # not my timeout
                    raise

        self.state_set(stack_status, reason)

    def delete(self):
        '''
        Delete all of the resources, and then the stack itself.
        '''
        self.state_set(self.DELETE_IN_PROGRESS, 'Stack deletion started')

        failures = []
        for res in reversed(self):
            result = res.destroy()
            if result:
                logger.error('Failed to delete %s error: %s' % (str(res),
                                                                result))
                failures.append(str(res))

        if failures:
            self.state_set(self.DELETE_FAILED,
                           'Failed to delete ' + ', '.join(failures))
        else:
            self.state_set(self.DELETE_COMPLETE, 'Deleted successfully')
            db_api.stack_delete(self.context, self.id)

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
                res.destroy()
            except Exception as ex:
                failed = True
                logger.error('delete: %s' % str(ex))

        for res in deps:
            if not failed:
                try:
                    res.create()
                except Exception as ex:
                    logger.exception('create')
                    failed = True
            else:
                res.state_set(res.CREATE_FAILED, 'Resource restart aborted')
        # TODO(asalkeld) if any of this fails we Should
        # restart the whole stack

    def resolve_static_data(self, snippet):
        return resolve_static_data(self.t, self.parameters, snippet)

    def resolve_runtime_data(self, snippet):
        return resolve_runtime_data(self.t, self.resources, snippet)


def resolve_static_data(template, parameters, snippet):
    '''
    Resolve static parameters, map lookups, etc. in a template.

    Example:

    >>> template = Template(format.parse_to_template(template_path))
    >>> parameters = Parameters('stack', template, {'KeyName': 'my_key'})
    >>> resolve_static_data(template, parameters, {'Ref': 'KeyName'})
    'my_key'
    '''
    return transform(snippet,
                     [functools.partial(template.resolve_param_refs,
                                        parameters=parameters),
                      template.resolve_availability_zones,
                      template.resolve_find_in_map,
                      template.reduce_joins])


def resolve_runtime_data(template, resources, snippet):
    return transform(snippet,
                     [functools.partial(template.resolve_resource_refs,
                                        resources=resources),
                      functools.partial(template.resolve_attributes,
                                        resources=resources),
                      template.resolve_joins,
                      template.resolve_base64])


def transform(data, transformations):
    '''
    Apply each of the transformation functions in the supplied list to the data
    in turn.
    '''
    for t in transformations:
        data = t(data)
    return data
