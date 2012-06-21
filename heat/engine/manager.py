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
import logging
import webob
import json
import urlparse
import re
import httplib
import eventlet

from heat import manager
from heat.db import api as db_api
from heat.common import config
from heat.common import utils as heat_utils
from heat.common import context as ctxtlib
from heat.engine import parser
from heat.engine import resources
from heat.engine import watchrule
from heat.openstack.common import timeutils

from novaclient.v1_1 import client
from novaclient.exceptions import BadRequest
from novaclient.exceptions import NotFound
from novaclient.exceptions import AuthorizationFailure

logger = logging.getLogger('heat.engine.manager')
greenpool = eventlet.GreenPool()

_param_key = re.compile(r'Parameters\.member\.(.*?)\.ParameterKey$')


def _extract_user_params(params):
    def get_param_pairs():
        for k in params:
            keymatch = _param_key.match(k)
            if keymatch:
                key = params[k]
                v = 'Parameters.member.%s.ParameterValue' % keymatch.group(1)
                try:
                    value = params[v]
                except KeyError:
                    logger.error('Could not apply parameter %s' % key)

                yield (key, value)

    return dict(get_param_pairs())


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

    def _authenticate(self, con):
        """ Authenticate against the 'heat' service.  This should be
            the first call made in an endpoint call.  I like to see this
            done explicitly so that it is clear there is an authentication
            request at the entry to the call.

            In the case of EC2 style authentication this will also set the
            username in the context so we can use it to key in the database.
        """

        if con.password is not None:
            nova = client.Client(con.username, con.password,
                                 con.tenant, con.auth_url,
                                 service_type='heat',
                                 service_name='heat')
            nova.authenticate()
        else:
            # We'll have to do AWS style auth which is more complex.
            # First step is to get a token from the AWS creds.
            headers = {'Content-Type': 'application/json'}

            o = urlparse.urlparse(con.aws_auth_uri)
            if o.scheme == 'http':
                conn = httplib.HTTPConnection(o.netloc)
            else:
                conn = httplib.HTTPSConnection(o.netloc)
            conn.request('POST', o.path, body=con.aws_creds, headers=headers)
            response = conn.getresponse().read()
            conn.close()

            result = json.loads(response)
            try:
                token_id = result['access']['token']['id']
                # We grab the username here because with token auth and EC2
                # we never get it normally.  We could pass it in but then We
                # are relying on user input to give us the correct username.
                # This one is the result of the authentication and is verified.
                username = result['access']['user']['username']
                con.username = username

                logger.info("AWS authentication successful.")
            except (AttributeError, KeyError):
                # FIXME: Should be 404 I think.
                logger.info("AWS authentication failure.")
                raise exception.AuthorizationFailure()

            nova = client.Client(con.service_user, con.service_password,
                                 con.tenant, con.auth_url,
                                 proxy_token=token_id,
                                 proxy_tenant_id=con.tenant_id,
                                 service_type='heat',
                                 service_name='heat')
            nova.authenticate()

    def list_stacks(self, context, params):
        """
        The list_stacks method is the end point that actually implements
        the 'list' command of the heat API.
        arg1 -> RPC context.
        arg2 -> Dict of http request parameters passed in from API side.
        """

        self._authenticate(context)

        res = {'stacks': []}
        stacks = db_api.stack_get_by_user(context)
        if stacks is None:
            return res
        for s in stacks:
            ps = parser.Stack(context, s.name,
                              s.raw_template.parsed_template.template,
                              s.id, _extract_user_params(params))
            mem = {}
            mem['StackId'] = "/".join([s.name, str(s.id)])
            mem['StackName'] = s.name
            mem['CreationTime'] = heat_utils.strtime(s.created_at)
            mem['TemplateDescription'] = ps.t.get('Description',
                                                   'No description')
            mem['StackStatus'] = s.status
            res['stacks'].append(mem)

        return res

    def show_stack(self, context, stack_name, params):
        """
        The show_stack method returns the attributes of one stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to see.
        arg3 -> Dict of http request parameters passed in from API side.
        """
        self._authenticate(context)

        res = {'stacks': []}
        s = db_api.stack_get_by_name(context, stack_name)
        if s:
            ps = parser.Stack(context, s.name,
                              s.raw_template.parsed_template.template,
                              s.id, _extract_user_params(params))
            mem = {}
            mem['StackId'] = "/".join([s.name, str(s.id)])
            mem['StackName'] = s.name
            mem['CreationTime'] = heat_utils.strtime(s.created_at)
            mem['LastUpdatedTimestamp'] = heat_utils.strtime(s.updated_at)
            mem['NotificationARNs'] = 'TODO'
            mem['Parameters'] = ps.t['Parameters']
            mem['TimeoutInMinutes'] = ps.t.get('Timeout', '60')
            mem['TemplateDescription'] = ps.t.get('Description',
                                                  'No description')
            mem['StackStatus'] = s.status
            mem['StackStatusReason'] = s.status_reason

            # only show the outputs on a completely created stack
            if s.status == ps.CREATE_COMPLETE:
                mem['Outputs'] = ps.get_outputs()

            res['stacks'].append(mem)

        return res

    def create_stack(self, context, stack_name, template, params):
        """
        The create_stack method creates a new stack using the template
        provided.
        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to create.
        arg3 -> Template of stack you want to create.
        arg4 -> Params passed from API.
        """
        logger.info('template is %s' % template)

        self._authenticate(context)

        if db_api.stack_get_by_name(None, stack_name):
            return {'Error': 'Stack already exists with that name.'}

        user_params = _extract_user_params(params)
        metadata_server = config.FLAGS.heat_metadata_server_url
        # We don't want to reset the stack template, so we are making
        # an instance just for validation.
        template_copy = deepcopy(template)
        stack_validator = parser.Stack(context, stack_name,
                                       template_copy, 0,
                                       user_params,
                                       metadata_server=metadata_server)
        response = stack_validator.validate()
        stack_validator = None
        template_copy = None
        if 'Malformed Query Response' in \
                response['ValidateTemplateResult']['Description']:
            return response

        stack = parser.Stack(context, stack_name, template, 0, user_params,
                             metadata_server=metadata_server)
        rt = {}
        rt['template'] = template
        rt['StackName'] = stack_name
        new_rt = db_api.raw_template_create(None, rt)

        new_creds = db_api.user_creds_create(context.to_dict())

        s = {}
        s['name'] = stack_name
        s['raw_template_id'] = new_rt.id
        s['user_creds_id'] = new_creds.id
        s['username'] = context.username
        new_s = db_api.stack_create(context, s)
        stack.id = new_s.id

        pt = {}
        pt['template'] = stack.t
        pt['raw_template_id'] = new_rt.id
        new_pt = db_api.parsed_template_create(None, pt)

        stack.parsed_template_id = new_pt.id
        greenpool.spawn_n(stack.create)

        return {'StackId': "/".join([new_s.name, str(new_s.id)])}

    def validate_template(self, context, template, params):
        """
        The validate_template method uses the stack parser to check
        the validity of a template.

        arg1 -> RPC context.
        arg3 -> Template of stack you want to create.
        arg4 -> Params passed from API.
        """

        self._authenticate(context)

        logger.info('validate_template')
        if template is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        try:
            s = parser.Stack(context, 'validate', template, 0,
                             _extract_user_params(params))
        except KeyError as ex:
            res = ('A Fn::FindInMap operation referenced '
                   'a non-existent map [%s]' % str(ex))

            response = {'ValidateTemplateResult': {
                        'Description': 'Malformed Query Response [%s]' % (res),
                        'Parameters': []}}
            return response

        res = s.validate()

        return res

    def get_template(self, context, stack_name, params):
        """
        Get the template.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to see.
        arg3 -> Dict of http request parameters passed in from API side.
        """
        self._authenticate(context)
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

        self._authenticate(context)

        st = db_api.stack_get_by_name(context, stack_name)
        if not st:
            return {'Error': 'No stack by that name'}

        logger.info('deleting stack %s' % stack_name)

        ps = parser.Stack(context, st.name,
                          st.raw_template.parsed_template.template,
                          st.id, _extract_user_params(params))
        greenpool.spawn_n(ps.delete)
        return None

    # Helper for list_events.  It's here so we can use it in tests.
    def parse_event(self, event):
        s = event.stack
        return {'EventId': event.id,
                'StackId': event.stack_id,
                'StackName': s.name,
                'Timestamp': str(event.created_at),
                'LogicalResourceId': event.logical_resource_id,
                'PhysicalResourceId': event.physical_resource_id,
                'ResourceType': event.resource_type,
                'ResourceStatusReason': event.resource_status_reason,
                'ResourceProperties': event.resource_properties,
                'ResourceStatus': event.name}

    def list_events(self, context, stack_name, params):
        """
        The list_events method lists all events associated with a given stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to get events for.
        arg3 -> Params passed from API.
        """

        self._authenticate(context)

        if stack_name is not None:
            st = db_api.stack_get_by_name(context, stack_name)
            if not st:
                return {'Error': 'No stack by that name'}

            events = db_api.event_get_all_by_stack(context, st.id)
        else:
            events = db_api.event_get_all_by_user(context)

        return {'events': [self.parse_event(e) for e in events]}

    def event_create(self, context, event):

        self._authenticate(context)

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
        self._authenticate(context)

        stack = db_api.stack_get_by_name(context, stack_name)
        if not stack:
            raise AttributeError('Unknown stack name')
        resource = db_api.resource_get_by_name_and_stack(context,
                                                         resource_name,
                                                         stack.id)
        if not resource:
            raise AttributeError('Unknown resource name')
        return format_resource_attributes(stack, resource)

    def describe_stack_resources(self, context, stack_name,
                                 physical_resource_id, logical_resource_id):
        self._authenticate(context)

        if stack_name:
            stack = db_api.stack_get_by_name(context, stack_name)
        else:
            resource = db_api.resource_get_by_physical_resource_id(context,
                    physical_resource_id)
            if not resource:
                msg = "The specified PhysicalResourceId doesn't exist"
                raise AttributeError(msg)
            stack = resource.stack

        if not stack:
            raise AttributeError("The specified stack doesn't exist")

        resources = []
        for r in stack.resources:
            if logical_resource_id and r.name != logical_resource_id:
                continue
            formatted = format_resource_attributes(stack, r)
            # this API call uses Timestamp instead of LastUpdatedTimestamp
            formatted['Timestamp'] = formatted['LastUpdatedTimestamp']
            del formatted['LastUpdatedTimestamp']
            resources.append(formatted)

        return resources

    def list_stack_resources(self, context, stack_name):
        self._authenticate(context)

        stack = db_api.stack_get_by_name(context, stack_name)
        if not stack:
            raise AttributeError('Unknown stack name')

        resources = []
        response_keys = ('ResourceStatus', 'LogicalResourceId',
                         'LastUpdatedTimestamp', 'PhysicalResourceId',
                         'ResourceType')
        for r in stack.resources:
            formatted = format_resource_attributes(stack, r)
            for key in formatted.keys():
                if not key in response_keys:
                    del formatted[key]
            resources.append(formatted)
        return resources

    def metadata_register_address(self, context, url):
        config.FLAGS.heat_metadata_server_url = url

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

    def metadata_get_resource(self, context, stack_name, resource_id):
        """
        Get the metadata for the given resource.
        """

        s = db_api.stack_get_by_name(None, stack_name)
        if not s:
            return ['stack', None]

        r = db_api.resource_get_by_name_and_stack(None, resource_id, s.id)
        if r is None:
            return ['resource', None]

        return [None, r.rsrc_metadata]

    def metadata_update(self, context, stack_name, resource_id, metadata):
        """
        Update the metadata for the given resource.
        """
        s = db_api.stack_get_by_name(None, stack_name)
        if not s:
            return ['stack', None]

        r = db_api.resource_get_by_name_and_stack(None, resource_id, s.id)
        if r is None:
            logger.warn("Resource not found %s:%s." % (stack_name,
                                                       resource_id))
            return ['resource', None]

        r.update_and_save({'rsrc_metadata': metadata})
        return [None, metadata]

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
                    ps = parser.Stack(ctxt, s.name,
                                      s.raw_template.parsed_template.template,
                                      s.id)
                    for a in wr.rule[action_map[new_state]]:
                        greenpool.spawn_n(ps[a].alarm)

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


def format_resource_attributes(stack, resource):
    """
    Return a representation of the given resource that mathes the API output
    expectations.
    """
    template = resource.parsed_template.template
    template_resources = template.get('Resources', {})
    resource_type = template_resources.get(resource.name, {}).get('Type', '')
    last_updated_time = resource.updated_at or resource.created_at
    return {
        'StackId': stack.id,
        'StackName': stack.name,
        'LogicalResourceId': resource.name,
        'PhysicalResourceId': resource.nova_instance or '',
        'ResourceType': resource_type,
        'LastUpdatedTimestamp': last_updated_time.isoformat(),
        'ResourceStatus': resource.state,
        'ResourceStatusReason': resource.state_description,
    }
