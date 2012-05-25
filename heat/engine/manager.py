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


import contextlib
from copy import deepcopy
import datetime
import functools
import os
import socket
import sys
import tempfile
import time
import traceback
import logging
import webob
from heat import manager
from heat.common import config
from heat.engine import parser
from heat.engine import resources
from heat.db import api as db_api
from heat.openstack.common import timeutils

logger = logging.getLogger('heat.engine.manager')


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

    def list_stacks(self, context, params):
        """
        The list_stacks method is the end point that actually implements
        the 'list' command of the heat API.
        arg1 -> RPC context.
        arg2 -> Dict of http request parameters passed in from API side.
        """
        logger.info('context is %s' % context)
        res = {'stacks': []}
        stacks = db_api.stack_get_all(None)
        if stacks == None:
            return res
        for s in stacks:
            ps = parser.Stack(s.name, s.raw_template.parsed_template.template,
                              s.id, params)
            mem = {}
            mem['stack_id'] = s.id
            mem['stack_name'] = s.name
            mem['created_at'] = str(s.created_at)
            mem['template_description'] = ps.t.get('Description',
                                                   'No description')
            mem['StackStatus'] = ps.t.get('stack_status', 'unknown')
            res['stacks'].append(mem)

        return res

    def show_stack(self, context, stack_name, params):
        """
        The show_stack method returns the attributes of one stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to see.
        arg3 -> Dict of http request parameters passed in from API side.
        """
        res = {'stacks': []}
        s = db_api.stack_get(None, stack_name)
        if s:
            ps = parser.Stack(s.name, s.raw_template.parsed_template.template,
                              s.id, params)
            mem = {}
            mem['stack_id'] = s.id
            mem['stack_name'] = s.name
            mem['creation_at'] = str(s.created_at)
            mem['updated_at'] = str(s.updated_at)
            mem['NotificationARNs'] = 'TODO'
            mem['Parameters'] = ps.t['Parameters']
            mem['StackStatusReason'] = 'TODO'
            mem['TimeoutInMinutes'] = 'TODO'
            mem['TemplateDescription'] = ps.t.get('Description',
                                                  'No description')
            mem['StackStatus'] = ps.t.get('stack_status', 'unknown')

            # only show the outputs on a completely created stack
            if ps.t['stack_status'] == ps.CREATE_COMPLETE:
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
        if db_api.stack_get(None, stack_name):
            return {'Error': 'Stack already exists with that name.'}

        metadata_server = config.FLAGS.heat_metadata_server_url
        # We don't want to reset the stack template, so we are making
        # an instance just for validation.
        template_copy = deepcopy(template)
        stack_validator = parser.Stack(stack_name, template_copy, 0, params,
                             metadata_server=metadata_server)
        response = stack_validator.validate()
        stack_validator = None
        template_copy = None
        if 'Malformed Query Response' in \
                response['ValidateTemplateResult']['Description']:
            return response['ValidateTemplateResult']['Description']

        stack = parser.Stack(stack_name, template, 0, params,
                             metadata_server=metadata_server)
        rt = {}
        rt['template'] = template
        rt['stack_name'] = stack_name
        new_rt = db_api.raw_template_create(None, rt)

        s = {}
        s['name'] = stack_name
        s['raw_template_id'] = new_rt.id
        new_s = db_api.stack_create(None, s)
        stack.id = new_s.id

        pt = {}
        pt['template'] = stack.t
        pt['raw_template_id'] = new_rt.id
        new_pt = db_api.parsed_template_create(None, pt)

        stack.parsed_template_id = new_pt.id
        stack.create()

        return {'stack': {'id': new_s.id, 'name': new_s.name,\
                'created_at': str(new_s.created_at)}}

    def validate_template(self, context, template, params):
        """
        The validate_template method uses the stack parser to check
        the validity of a template.

        arg1 -> RPC context.
        arg3 -> Template of stack you want to create.
        arg4 -> Params passed from API.
        """

        logger.info('validate_template')
        if template is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        try:
            s = parser.Stack('validate', template, 0, params)
        except KeyError:
            res = 'A Fn::FindInMap operation referenced'\
                  'a non-existent map [%s]' % sys.exc_value

            response = {'ValidateTemplateResult': {
                        'Description': 'Malformed Query Response [%s]' % (res),
                        'Parameters': []}}
            return response

        res = s.validate()

        return res

    def delete_stack(self, context, stack_name, params):
        """
        The delete_stack method deletes a given stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to delete.
        arg3 -> Params passed from API.
        """
        st = db_api.stack_get(None, stack_name)
        if not st:
            return {'Error': 'No stack by that name'}

        logger.info('deleting stack %s' % stack_name)

        ps = parser.Stack(st.name, st.raw_template.parsed_template.template,
                          st.id, params)
        ps.delete()
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

    def list_events(self, context, stack_name):
        """
        The list_events method lists all events associated with a given stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to get events for.
        """
        if stack_name is not None:
            st = db_api.stack_get(None, stack_name)
            if not st:
                return {'Error': 'No stack by that name'}

            events = db_api.event_get_all_by_stack(None, st.id)
        else:
            events = db_api.event_get_all(None)

        return {'events': [self.parse_event(e) for e in events]}

    def event_create(self, context, event):
        stack_name = event['stack']
        resource_name = event['resource']
        stack = db_api.stack_get(None, stack_name)
        resource = db_api.resource_get_by_name_and_stack(None, resource_name,
                                                         stack.id)
        if not resource:
            return ['Unknown resource', None]
        new_event = {
            'name': event['message'],
            'resource_status_reason': event['reason'],
            'stack_id': stack.id,
            'logical_resource_id': resource.name,
            'physical_resource_id': None,
            'resource_type': event['resource_type'],
            'resource_properties': {},
        }
        try:
            result = db_api.event_create(None, new_event)
            new_event['id'] = result.id
            return [None, new_event]
        except Exception as ex:
            logger.warn('db error %s' % str(ex))
            msg = 'Error creating event'
            return [msg, None]

    def metadata_register_address(self, context, url):
        config.FLAGS.heat_metadata_server_url = url

    def metadata_list_stacks(self, context):
        """
        Return the names of the stacks registered with Heat.
        """
        stacks = db_api.stack_get_all(None)
        return [s.name for s in stacks]

    def metadata_list_resources(self, context, stack_name):
        """
        Return the resource IDs of the given stack.
        """
        stack = db_api.stack_get(None, stack_name)
        if stack:
            return [r.name for r in stack.resources]
        else:
            return None

    def metadata_get_resource(self, context, stack_name, resource_id):
        """
        Get the metadata for the given resource.
        """
        s = db_api.stack_get(None, stack_name)
        if not s:
            return ['stack', None]

        template = s.raw_template.parsed_template.template
        if not resource_id in template.get('Resources', {}):
            return ['resource', None]

        metadata = template['Resources'][resource_id].get('Metadata', {})
        return [None, metadata]

    def metadata_update(self, context, stack_name, resource_id, metadata):
        """
        Update the metadata for the given resource.
        """
        s = db_api.stack_get(None, stack_name)
        if not s:
            return ['stack', None]
        pt_id = s.raw_template.parsed_template.id

        pt = db_api.parsed_template_get(None, pt_id)
        if not resource_id in pt.template.get('Resources', {}):
            return ['resource', None]

        # TODO(shadower) deep copy of the template is required here. Without
        # it, we directly modify parsed_template.template by assigning the new
        # metadata. When we then call parsed_template.update_and_save, the
        # session will detect no changes and thus not update the database.
        # Just updating the values and calling save didn't seem to work either.
        # There's probably an idiomatic way I'm missing right now.
        t = deepcopy(pt.template)
        t['Resources'][resource_id]['Metadata'] = metadata
        pt.template = t
        pt.save()
        return [None, metadata]

    def do_data_cmp(self, rule, data, threshold):
        op = rule['ComparisonOperator']
        if op == 'GreaterThanThreshold':
            return data > threshold
        elif op == 'GreaterThanOrEqualToThreshold':
            return data >= threshold
        elif op == 'LessThanThreshold':
            return data < threshold
        elif op == 'LessThanOrEqualToThreshold':
            return data <= threshold
        else:
            return False

    def do_data_calc(self, rule, rolling, metric):

        stat = rule['Statistic']
        if stat == 'Maximum':
            if metric > rolling:
                return metric
            else:
                return rolling
        elif stat == 'Minimum':
            if metric < rolling:
                return metric
            else:
                return rolling
        else:
            return metric + rolling

    @manager.periodic_task
    def _periodic_watcher_task(self, context):

        now = timeutils.utcnow()
        wrs = db_api.watch_rule_get_all(context)
        for wr in wrs:
            logger.debug('_periodic_watcher_task %s' % wr.name)
            # has enough time progressed to run the rule
            dt_period = datetime.timedelta(seconds=int(wr.rule['Period']))
            if now < (wr.last_evaluated + dt_period):
                continue

            # get dataset ordered by creation_at
            # - most recient first
            periods = int(wr.rule['EvaluationPeriods'])

            # TODO fix this
            # initial assumption: all samples are in this period
            period = int(wr.rule['Period'])
            #wds = db_api.watch_data_get_all(context, wr.id)
            wds = wr.watch_data

            stat = wr.rule['Statistic']
            data = 0
            samples = 0
            for d in wds:
                if d.created_at < wr.last_evaluated:
                    logger.debug('ignoring old data %s: %s < %s' % \
                                 (wr.rule['MetricName'],
                                  str(d.created_at),
                                  str(wr.last_evaluated)))
                    continue
                samples = samples + 1
                metric = 1
                data = samples
                if stat != 'SampleCount':
                    metric = int(d.data[wr.rule['MetricName']]['Value'])
                    data = self.do_data_calc(wr.rule, data, metric)
                logger.debug('%s: %d/%d' % (wr.rule['MetricName'],
                                            metric, data))

            if stat == 'Average' and samples > 0:
                data = data / samples

            alarming = self.do_data_cmp(wr.rule, data,
                                        int(wr.rule['Threshold']))
            logger.debug('%s: %d/%d => %d (current state:%s)' % \
                         (wr.rule['MetricName'],
                          int(wr.rule['Threshold']),
                          data, alarming, wr.state))
            if alarming and wr.state != 'ALARM':
                wr.state = 'ALARM'
                wr.save()
                logger.info('ALARM> stack:%s, watch_name:%s',
                            wr.stack_name, wr.name)
                #s = db_api.stack_get(None, wr.stack_name)
                #if s:
                #    ps = parser.Stack(s.name,
                #                      s.raw_template.parsed_template.template,
                #                      s.id,
                #                      params)
                #    for a in wr.rule['AlarmActions']:
                #        ps.resources[a].alarm()

            elif not alarming and wr.state == 'ALARM':
                wr.state = 'NORMAL'
                wr.save()
                logger.info('NORMAL> stack:%s, watch_name:%s',
                            wr.stack_name, wr.name)

            wr.last_evaluated = now

    def create_watch_data(self, context, watch_name, stats_data):
        '''
        This could be used by CloudWatch and WaitConditions
        and treat HA service events like any other CloudWatch.
        '''

        wr = db_api.watch_rule_get(context, watch_name)
        if wr is None:
            return ['NoSuch Watch Rule', None]

        if not wr.rule['MetricName'] in stats_data:
            return ['MetricName %s missing' % wr.rule['MetricName'], None]

        watch_data = {
            'data': stats_data,
            'watch_rule_id': wr.id
        }
        wd = db_api.watch_data_create(context, watch_data)

        return [None, wd.data]
