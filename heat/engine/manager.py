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
from heat.common import context as ctxtlib
from heat.engine import api
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

    def show_stack(self, context, stack_name, params):
        """
        The show_stack method returns the attributes of one stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to see, or None to see all
        arg3 -> Dict of http request parameters passed in from API side.
        """
        auth.authenticate(context)

        if stack_name is not None:
            s = db_api.stack_get_by_name(context, stack_name)
            if s:
                stacks = [s]
            else:
                raise AttributeError('Unknown stack name')
        else:
            stacks = db_api.stack_get_by_user(context) or []

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

        auth.authenticate(context)

        if db_api.stack_get_by_name(None, stack_name):
            return {'Error': 'Stack already exists with that name.'}

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

        return {'StackName': stack.name, 'StackId': stack.id}

    def validate_template(self, context, template, params):
        """
        The validate_template method uses the stack parser to check
        the validity of a template.

        arg1 -> RPC context.
        arg3 -> Template of stack you want to create.
        arg4 -> Params passed from API.
        """

        auth.authenticate(context)

        logger.info('validate_template')
        if template is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        stack_name = 'validate'
        try:
            tmpl = parser.Template(template)
            user_params = parser.Parameters(stack_name, tmpl, params)
            s = parser.Stack(context, stack_name, tmpl, user_params)
        except KeyError as ex:
            res = ('A Fn::FindInMap operation referenced '
                   'a non-existent map [%s]' % str(ex))

            result = {'Description': 'Malformed Query Response [%s]' % (res),
                      'Parameters': []}
        else:
            result = s.validate()

        return {'ValidateTemplateResult': result}

    def get_template(self, context, stack_name, params):
        """
        Get the template.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to see.
        arg3 -> Dict of http request parameters passed in from API side.
        """
        auth.authenticate(context)
        s = db_api.stack_get_by_name(context, stack_name)
        if s:
            return s.raw_template.template
        return None

    def delete_stack(self, context, stack_name, params):
        """
        The delete_stack method deletes a given stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to delete.
        arg3 -> Params passed from API.
        """

        auth.authenticate(context)

        st = db_api.stack_get_by_name(context, stack_name)
        if not st:
            raise AttributeError('Unknown stack name')

        logger.info('deleting stack %s' % stack_name)

        stack = parser.Stack.load(context, st.id)
        greenpool.spawn_n(stack.delete)
        return None

    def list_events(self, context, stack_name, params):
        """
        The list_events method lists all events associated with a given stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to get events for.
        arg3 -> Params passed from API.
        """

        auth.authenticate(context)

        if stack_name is not None:
            st = db_api.stack_get_by_name(context, stack_name)
            if not st:
                raise AttributeError('Unknown stack name')

            events = db_api.event_get_all_by_stack(context, st.id)
        else:
            events = db_api.event_get_all_by_user(context)

        return {'events': [api.format_event(e) for e in events]}

    def event_create(self, context, event):

        auth.authenticate(context)

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

    def describe_stack_resource(self, context, stack_name, resource_name):
        auth.authenticate(context)

        s = db_api.stack_get_by_name(context, stack_name)
        if not s:
            raise AttributeError('Unknown stack name')

        stack = parser.Stack.load(context, s.id)
        if resource_name not in stack:
            raise AttributeError('Unknown resource name')

        resource = stack[resource_name]
        if resource.id is None:
            raise AttributeError('Resource not created')

        return api.format_stack_resource(stack[resource_name])

    def describe_stack_resources(self, context, stack_name,
                                 physical_resource_id, logical_resource_id):
        auth.authenticate(context)

        if stack_name is not None:
            s = db_api.stack_get_by_name(context, stack_name)
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

    def list_stack_resources(self, context, stack_name):
        auth.authenticate(context)

        s = db_api.stack_get_by_name(context, stack_name)
        if not s:
            raise AttributeError('Unknown stack name')

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
            return ['stack', None]

        stack = parser.Stack.load(None, s.id)
        if resource_name not in stack:
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
        wrs = db_api.watch_rule_get_all(context)
        for wr in wrs:
            # has enough time progressed to run the rule
            dt_period = datetime.timedelta(seconds=int(wr.rule['Period']))
            if now < (wr.last_evaluated + dt_period):
                continue

            self.run_rule(context, wr, now)

    def run_rule(self, context, wr, now=timeutils.utcnow()):
        action_map = {'ALARM': 'AlarmActions',
                      'NORMAL': 'OKActions',
                      'NODATA': 'InsufficientDataActions'}

        watcher = watchrule.WatchRule(wr.rule, wr.watch_data,
                                      wr.last_evaluated, now)
        new_state = watcher.get_alarm_state()

        if new_state != wr.state:
            wr.state = new_state
            wr.save()
            logger.warn('WATCH: stack:%s, watch_name:%s %s',
                        wr.stack_name, wr.name, new_state)

            if not action_map[new_state] in wr.rule:
                logger.info('no action for new state %s',
                            new_state)
            else:
                s = db_api.stack_get_by_name(None, wr.stack_name)
                if s:
                    user_creds = db_api.user_creds_get(s.user_creds_id)
                    ctxt = ctxtlib.RequestContext.from_dict(dict(user_creds))
                    stack = parser.Stack.load(ctxt, s.id)
                    for a in wr.rule[action_map[new_state]]:
                        greenpool.spawn_n(stack[a].alarm)

        wr.last_evaluated = now

    def create_watch_data(self, context, watch_name, stats_data):
        '''
        This could be used by CloudWatch and WaitConditions
        and treat HA service events like any other CloudWatch.
        '''
        wr = db_api.watch_rule_get(None, watch_name)
        if wr is None:
            logger.warn('NoSuch watch:%s' % (watch_name))
            return ['NoSuch Watch Rule', None]

        if not wr.rule['MetricName'] in stats_data:
            logger.warn('new data has incorrect metric:%s' %
                        (wr.rule['MetricName']))
            return ['MetricName %s missing' % wr.rule['MetricName'], None]

        watch_data = {
            'data': stats_data,
            'watch_rule_id': wr.id
        }
        wd = db_api.watch_data_create(None, watch_data)
        logger.debug('new watch:%s data:%s' % (watch_name, str(wd.data)))
        if wr.rule['Statistic'] == 'SampleCount':
            self.run_rule(None, wr)

        return [None, wd.data]
