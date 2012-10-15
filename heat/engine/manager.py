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


from copy import deepcopy
import datetime
import webob
import json
import urlparse
import httplib
import eventlet

from heat import manager
from heat.db import api as db_api
from heat.common import config
from heat.common import utils as heat_utils
from heat.engine import api
from heat.engine import identifier
from heat.engine import parser
from heat.engine import resources
from heat.engine import watchrule
from heat.engine import auth

from heat.openstack.common import cfg
from heat.openstack.common import timeutils
from heat.openstack.common import log as logging

from novaclient.v1_1 import client
from novaclient.exceptions import BadRequest
from novaclient.exceptions import NotFound
from novaclient.exceptions import AuthorizationFailure

logger = logging.getLogger('heat.engine.manager')
greenpool = eventlet.GreenPool()


class EngineManager(manager.Manager):
    """
    Manages the running instances from creation to destruction.
    All the methods in here are called from the RPC backend.  This is
    all done dynamically so if a call is made via RPC that does not
    have a corresponding method here, an exception will be thrown when
    it attempts to call into this class.  Arguments to these methods
    are also dynamically added and will be named as keyword arguments
    by the RPC caller.
    """

    def __init__(self, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        pass

    def identify_stack(self, context, stack_name):
        """
        The identify_stack method returns the full stack identifier for a
        single, live stack given the stack name.
        arg1 -> RPC context.
        arg2 -> Name of the stack to look up.
        """
        s = db_api.stack_get_by_name(context, stack_name)
        if s:
            stack = parser.Stack.load(context, s.id)
            return dict(stack.identifier())
        else:
            raise AttributeError('Unknown stack name')

    def _get_stack(self, context, stack_identity):
        identity = identifier.HeatIdentifier(**stack_identity)

        if identity.tenant != context.tenant:
            raise AttributeError('Invalid tenant')

        s = db_api.stack_get(context, identity.stack_id)

        if s is None:
            raise AttributeError('Stack not found')

        if identity.path or s.name != identity.stack_name:
            raise AttributeError('Invalid stack ID')

        return s

    def show_stack(self, context, stack_identity):
        """
        The show_stack method returns the attributes of one stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to see, or None to see all
        """
        if stack_identity is not None:
            stacks = [self._get_stack(context, stack_identity)]
        else:
            stacks = db_api.stack_get_by_tenant(context) or []

        def format_stack_detail(s):
            stack = parser.Stack.load(context, s.id)
            return api.format_stack(stack)

        return {'stacks': [format_stack_detail(s) for s in stacks]}

    def create_stack(self, context, stack_name, template, params, args):
        """
        The create_stack method creates a new stack using the template
        provided.
        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to create.
        arg3 -> Template of stack you want to create.
        arg4 -> Stack Input Params
        arg4 -> Request parameters/args passed from API
        """
        logger.info('template is %s' % template)

        if db_api.stack_get_by_name(None, stack_name):
            raise AttributeError('Stack already exists with that name')

        tmpl = parser.Template(template)

        # Extract the template parameters, and any common query parameters
        template_params = parser.Parameters(stack_name, tmpl, params)
        common_params = api.extract_args(args)

        stack = parser.Stack(context, stack_name, tmpl, template_params,
                             **common_params)

        response = stack.validate()
        if response['Description'] != 'Successfully validated':
            return response

        stack_id = stack.store()
        greenpool.spawn_n(stack.create)

        return dict(stack.identifier())

    def update_stack(self, context, stack_identity, template, params, args):
        """
        The update_stack method updates an existing stack based on the
        provided template and parameters.
        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to create.
        arg3 -> Template of stack you want to create.
        arg4 -> Stack Input Params
        arg4 -> Request parameters/args passed from API
        """
        logger.info('template is %s' % template)

        # Get the database representation of the existing stack
        db_stack = self._get_stack(context, stack_identity)

        current_stack = parser.Stack.load(context, db_stack.id)

        # Now parse the template and any parameters for the updated
        # stack definition.
        tmpl = parser.Template(template)
        stack_name = current_stack.name
        template_params = parser.Parameters(stack_name, tmpl, params)
        common_params = api.extract_args(args)

        updated_stack = parser.Stack(context, stack_name, tmpl,
                                     template_params, **common_params)

        response = updated_stack.validate()
        if response['Description'] != 'Successfully validated':
            return response

        greenpool.spawn_n(current_stack.update, updated_stack)

        return dict(current_stack.identifier())

    def validate_template(self, context, template, params):
        """
        The validate_template method uses the stack parser to check
        the validity of a template.

        arg1 -> RPC context.
        arg3 -> Template of stack you want to create.
        arg4 -> Stack Input Params
        """
        logger.info('validate_template')
        if template is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        tmpl = parser.Template(template)
        resources = template.get('Resources', [])

        if not resources:
            return {'Error': 'At least one Resources member must be defined.'}

        for res in resources.values():
            if not res.get('Type'):
                return {'Error':
                        'Every Resources object must contain a Type member.'}

        parameters = []
        for param_key, param in template.get('Parameters', {}).items():
            parameters.append({
                'NoEcho': param.get('NoEcho', 'false'),
                'ParameterKey': param_key,
                'Description': param.get('Description', '')
            })

        result = {
            'Description': template.get('Description', ''),
            'Parameters': parameters,
        }
        return {'ValidateTemplateResult': result}

    def get_template(self, context, stack_identity):
        """
        Get the template.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to see.
        """
        s = self._get_stack(context, stack_identity)
        if s:
            return s.raw_template.template
        return None

    def delete_stack(self, context, stack_identity):
        """
        The delete_stack method deletes a given stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to delete.
        """
        st = self._get_stack(context, stack_identity)

        logger.info('deleting stack %s' % st.name)

        stack = parser.Stack.load(context, st.id)
        greenpool.spawn_n(stack.delete)
        return None

    def list_events(self, context, stack_identity):
        """
        The list_events method lists all events associated with a given stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to get events for.
        """
        if stack_identity is not None:
            st = self._get_stack(context, stack_identity)

            events = db_api.event_get_all_by_stack(context, st.id)
        else:
            events = db_api.event_get_all_by_tenant(context)

        return {'events': [api.format_event(context, e) for e in events]}

    def event_create(self, context, event):
        stack_name = event['stack']
        resource_name = event['resource']
        stack = db_api.stack_get_by_name(context, stack_name)
        resource = db_api.resource_get_by_name_and_stack(context,
                                                         resource_name,
                                                         stack.id)
        if not resource:
            return ['Unknown resource', None]
        new_event = {
            'name': event['message'],
            'resource_status_reason': event['reason'],
            'StackId': stack.id,
            'LogicalResourceId': resource.name,
            'PhysicalResourceId': None,
            'ResourceType': event['resource_type'],
            'ResourceProperties': {},
        }
        try:
            result = db_api.event_create(context, new_event)
            new_event['id'] = result.id
            return [None, new_event]
        except Exception as ex:
            logger.warn('db error %s' % str(ex))
            msg = 'Error creating event'
            return [msg, None]

    def describe_stack_resource(self, context, stack_identity, resource_name):
        s = self._get_stack(context, stack_identity)

        stack = parser.Stack.load(context, s.id)
        if resource_name not in stack:
            raise AttributeError('Unknown resource name')

        resource = stack[resource_name]
        if resource.id is None:
            raise AttributeError('Resource not created')

        return api.format_stack_resource(stack[resource_name])

    def describe_stack_resources(self, context, stack_identity,
                                 physical_resource_id, logical_resource_id):
        if stack_identity is not None:
            s = self._get_stack(context, stack_identity)
        else:
            rs = db_api.resource_get_by_physical_resource_id(context,
                    physical_resource_id)
            if not rs:
                msg = "The specified PhysicalResourceId doesn't exist"
                raise AttributeError(msg)
            s = rs.stack

        if not s:
            raise AttributeError("The specified stack doesn't exist")

        stack = parser.Stack.load(context, s.id)

        if logical_resource_id is not None:
            name_match = lambda r: r.name == logical_resource_id
        else:
            name_match = lambda r: True

        return [api.format_stack_resource(resource)
                for resource in stack if resource.id is not None and
                                         name_match(resource)]

    def list_stack_resources(self, context, stack_identity):
        s = self._get_stack(context, stack_identity)

        stack = parser.Stack.load(context, s.id)

        return [api.format_stack_resource(resource)
                for resource in stack if resource.id is not None]

    def metadata_register_address(self, context, url):
        cfg.CONF.heat_metadata_server_url = url

    def metadata_list_stacks(self, context):
        """
        Return the names of the stacks registered with Heat.
        """
        stacks = db_api.stack_get_all(context)
        return [s.name for s in stacks]

    def metadata_list_resources(self, context, stack_name):
        """
        Return the resource IDs of the given stack.
        """
        stack = db_api.stack_get_by_name(None, stack_name)
        if stack:
            return [res.name for res in stack.resources]
        else:
            return None

    def metadata_get_resource(self, context, stack_name, resource_name):
        """
        Get the metadata for the given resource.
        """

        s = db_api.stack_get_by_name(None, stack_name)
        if not s:
            logger.warn("Stack %s not found" % stack_name)
            return ['stack', None]

        stack = parser.Stack.load(None, s.id)
        if resource_name not in stack:
            logger.warn("Resource not found %s:%s." % (stack_name,
                                                       resource_name))
            return ['resource', None]

        resource = stack[resource_name]

        return [None, resource.metadata]

    def metadata_update(self, context, stack_id, resource_name, metadata):
        """
        Update the metadata for the given resource.
        """
        s = db_api.stack_get(None, stack_id)
        if s is None:
            logger.warn("Stack %s not found" % stack_id)
            return ['stack', None]

        stack = parser.Stack.load(None, s.id)
        if resource_name not in stack:
            logger.warn("Resource not found %s:%s." % (stack_id,
                                                       resource_name))
            return ['resource', None]

        resource = stack[resource_name]
        resource.metadata = metadata

        return [None, resource.metadata]

    @manager.periodic_task
    def _periodic_watcher_task(self, context):

        now = timeutils.utcnow()
        try:
            wrn = [w.name for w in db_api.watch_rule_get_all(context)]
        except Exception as ex:
            logger.warn('periodic_task db error (%s) %s' %
                        ('watch rule removed?', str(ex)))
            return
        for wr in wrn:
            rule = watchrule.WatchRule.load(context, wr)
            rule.evaluate()

    def create_watch_data(self, context, watch_name, stats_data):
        '''
        This could be used by CloudWatch and WaitConditions
        and treat HA service events like any other CloudWatch.
        '''
        rule = watchrule.WatchRule.load(context, watch_name)
        rule.create_watch_data(stats_data)
        logger.debug('new watch:%s data:%s' % (watch_name, str(stats_data)))
        return stats_data

    def show_watch(self, context, watch_name):
        '''
        The show_watch method returns the attributes of one watch/alarm
        arg1 -> RPC context.
        arg2 -> Name of the watch you want to see, or None to see all
        '''
        if watch_name:
            wrn = [watch_name]
        else:
            try:
                wrn = [w.name for w in db_api.watch_rule_get_all(context)]
            except Exception as ex:
                logger.warn('show_watch (all) db error %s' % str(ex))
                return

        wrs = [watchrule.WatchRule.load(context, w) for w in wrn]
        result = [api.format_watch(w) for w in wrs]
        return result

    def show_watch_metric(self, context, namespace=None, metric_name=None):
        '''
        The show_watch method returns the datapoints for a metric
        arg1 -> RPC context.
        arg2 -> Name of the namespace you want to see, or None to see all
        arg3 -> Name of the metric you want to see, or None to see all
        '''

        # DB API and schema does not yet allow us to easily query by
        # namespace/metric, but we will want this at some point
        # for now, the API can query all metric data and filter locally
        if namespace != None or metric_name != None:
            logger.error("Filtering by namespace/metric not yet supported")
            return

        try:
            wds = db_api.watch_data_get_all(context)
        except Exception as ex:
            logger.warn('show_metric (all) db error %s' % str(ex))
            return

        result = [api.format_watch_data(w) for w in wds]
        return result

    def set_watch_state(self, context, watch_name, state):
        '''
        Temporarily set the state of a given watch
        arg1 -> RPC context.
        arg2 -> Name of the watch
        arg3 -> State (must be one defined in WatchRule class
        '''
        wr = watchrule.WatchRule.load(context, watch_name)
        wr.set_watch_state(state)

        # Return the watch with the state overriden to indicate success
        # We do not update the timestamps as we are not modifying the DB
        result = api.format_watch(wr)
        result[api.WATCH_STATE_VALUE] = state
        return result
