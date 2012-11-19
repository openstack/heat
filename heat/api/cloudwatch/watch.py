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

"""
endpoint for heat AWS-compatible CloudWatch API
"""
from heat.api.aws import exception
from heat.api.aws import utils as api_utils
from heat.common import wsgi
from heat.engine import rpcapi as engine_rpcapi
import heat.engine.api as engine_api

import heat.openstack.common.rpc.common as rpc_common
from heat.openstack.common import log as logging

logger = logging.getLogger('heat.api.cloudwatch.controller')


class WatchController(object):

    """
    WSGI controller for CloudWatch resource in heat API
    Implements the API actions
    """

    def __init__(self, options):
        self.options = options
        self.engine_rpcapi = engine_rpcapi.EngineAPI()

    @staticmethod
    def _reformat_dimensions(dims):
        '''
        Reformat dimensions list into AWS API format
        Parameter dims is a list of dicts
        '''
        newdims = []
        for count, d in enumerate(dims, 1):
            for key in d.keys():
                newdims.append({'Name': key, 'Value': d[key]})
        return newdims

    def delete_alarms(self, req):
        """
        Implements DeleteAlarms API action
        """
        return exception.HeatAPINotImplementedError()

    def describe_alarm_history(self, req):
        """
        Implements DescribeAlarmHistory API action
        """
        return exception.HeatAPINotImplementedError()

    def describe_alarms(self, req):
        """
        Implements DescribeAlarms API action
        """

        def format_metric_alarm(a):
            """
            Reformat engine output into the AWS "MetricAlarm" format
            """
            keymap = {
            engine_api.WATCH_ACTIONS_ENABLED: 'ActionsEnabled',
            engine_api.WATCH_ALARM_ACTIONS: 'AlarmActions',
            engine_api.WATCH_TOPIC: 'AlarmArn',
            engine_api.WATCH_UPDATED_TIME:
                'AlarmConfigurationUpdatedTimestamp',
            engine_api.WATCH_DESCRIPTION: 'AlarmDescription',
            engine_api.WATCH_NAME: 'AlarmName',
            engine_api.WATCH_COMPARISON: 'ComparisonOperator',
            engine_api.WATCH_DIMENSIONS: 'Dimensions',
            engine_api.WATCH_PERIODS: 'EvaluationPeriods',
            engine_api.WATCH_INSUFFICIENT_ACTIONS: 'InsufficientDataActions',
            engine_api.WATCH_METRIC_NAME: 'MetricName',
            engine_api.WATCH_NAMESPACE: 'Namespace',
            engine_api.WATCH_OK_ACTIONS: 'OKActions',
            engine_api.WATCH_PERIOD: 'Period',
            engine_api.WATCH_STATE_REASON: 'StateReason',
            engine_api.WATCH_STATE_REASON_DATA: 'StateReasonData',
            engine_api.WATCH_STATE_UPDATED_TIME: 'StateUpdatedTimestamp',
            engine_api.WATCH_STATE_VALUE: 'StateValue',
            engine_api.WATCH_STATISTIC: 'Statistic',
            engine_api.WATCH_THRESHOLD: 'Threshold',
            engine_api.WATCH_UNIT: 'Unit'}

            # AWS doesn't return StackName in the main MetricAlarm
            # structure, so we add StackName as a dimension to all responses
            a[engine_api.WATCH_DIMENSIONS].append({'StackName':
                                           a[engine_api.WATCH_STACK_NAME]})

            # Reformat dimensions list into AWS API format
            a[engine_api.WATCH_DIMENSIONS] = self._reformat_dimensions(
                                             a[engine_api.WATCH_DIMENSIONS])

            return api_utils.reformat_dict_keys(keymap, a)

        con = req.context
        parms = dict(req.params)
        try:
            name = parms['AlarmName']
        except KeyError:
            name = None

        try:
            watch_list = self.engine_rpcapi.show_watch(con, watch_name=name)
        except rpc_common.RemoteError as ex:
            return exception.map_remote_error(ex)

        res = {'MetricAlarms': [format_metric_alarm(a)
                                   for a in watch_list]}

        result = api_utils.format_response("DescribeAlarms", res)
        return result

    def describe_alarms_for_metric(self, req):
        """
        Implements DescribeAlarmsForMetric API action
        """
        return exception.HeatAPINotImplementedError()

    def disable_alarm_actions(self, req):
        """
        Implements DisableAlarmActions API action
        """
        return exception.HeatAPINotImplementedError()

    def enable_alarm_actions(self, req):
        """
        Implements EnableAlarmActions API action
        """
        return exception.HeatAPINotImplementedError()

    def get_metric_statistics(self, req):
        """
        Implements GetMetricStatistics API action
        """
        return exception.HeatAPINotImplementedError()

    def list_metrics(self, req):
        """
        Implements ListMetrics API action
        Lists metric datapoints associated with a particular alarm,
        or all alarms if none specified
        """
        def format_metric_data(d, fil={}):
            """
            Reformat engine output into the AWS "Metric" format
            Takes an optional filter dict, which is traversed
            so a metric dict is only returned if all keys match
            the filter dict
            """
            dimensions = [
                {'AlarmName': d[engine_api.WATCH_DATA_ALARM]},
                {'Timestamp': d[engine_api.WATCH_DATA_TIME]}
            ]
            for key in d[engine_api.WATCH_DATA]:
                dimensions.append({key: d[engine_api.WATCH_DATA][key]})

            newdims = self._reformat_dimensions(dimensions)

            result = {
                'MetricName': d[engine_api.WATCH_DATA_METRIC],
                'Dimensions': newdims,
                'Namespace': d[engine_api.WATCH_DATA_NAMESPACE],
            }

            for f in fil:
                try:
                    value = result[f]
                    if value != fil[f]:
                        # Filter criteria not met, return None
                        return
                except KeyError:
                    logger.warning("Invalid filter key %s, ignoring" % f)

            return result

        con = req.context
        parms = dict(req.params)
        # FIXME : Don't yet handle filtering by Dimensions
        filter_result = dict((k, v) for (k, v) in parms.iteritems() if k in
                             ("MetricName", "Namespace"))
        logger.debug("filter parameters : %s" % filter_result)

        try:
            # Engine does not currently support query by namespace/metric
            # so we pass None/None and do any filtering locally
            watch_data = self.engine_rpcapi.show_watch_metric(con,
                                                              namespace=None,
                                                              metric_name=None)
        except rpc_common.RemoteError as ex:
            return exception.map_remote_error(ex)

        res = {'Metrics': []}
        for d in watch_data:
            metric = format_metric_data(d, filter_result)
            if metric:
                res['Metrics'].append(metric)

        result = api_utils.format_response("ListMetrics", res)
        return result

    def put_metric_alarm(self, req):
        """
        Implements PutMetricAlarm API action
        """
        return exception.HeatAPINotImplementedError()

    def put_metric_data(self, req):
        """
        Implements PutMetricData API action
        """

        con = req.context
        parms = dict(req.params)
        namespace = api_utils.get_param_value(parms, 'Namespace')

        # Extract data from the request so we can pass it to the engine
        # We have to do this in two passes, because the AWS
        # query format nests the dimensions within the MetricData
        # query-parameter-list (see AWS PutMetricData docs)
        # extract_param_list gives a list-of-dict, which we then
        # need to process (each dict) for dimensions
        metric_data = api_utils.extract_param_list(parms, prefix='MetricData')
        if not len(metric_data):
            logger.error("Request does not contain required MetricData")
            return exception.HeatMissingParameterError("MetricData list")

        watch_name = None
        dimensions = []
        for p in metric_data:
            dimension = api_utils.extract_param_pairs(p,
                                                   prefix='Dimensions',
                                                   keyname='Name',
                                                   valuename='Value')
            if 'AlarmName' in dimension:
                watch_name = dimension['AlarmName']
            else:
                dimensions.append(dimension)

        # We expect an AlarmName dimension as currently the engine
        # implementation requires metric data to be associated
        # with an alarm.  When this is fixed, we can simply
        # parse the user-defined dimensions and add the list to
        # the metric data
        if not watch_name:
            logger.error("Request does not contain AlarmName dimension!")
            return exception.HeatMissingParameterError("AlarmName dimension")

        # Extract the required data from the metric_data
        # and format dict to pass to engine
        data = {'Namespace': namespace,
                api_utils.get_param_value(metric_data[0], 'MetricName'): {
                    'Unit': api_utils.get_param_value(metric_data[0], 'Unit'),
                    'Value': api_utils.get_param_value(metric_data[0],
                                                       'Value'),
                    'Dimensions': dimensions}}

        try:
            res = self.engine_rpcapi.create_watch_data(con, watch_name, data)
        except rpc_common.RemoteError as ex:
            return exception.map_remote_error(ex)

        result = {'ResponseMetadata': None}
        return api_utils.format_response("PutMetricData", result)

    def set_alarm_state(self, req):
        """
        Implements SetAlarmState API action
        """
        # Map from AWS state names to those used in the engine
        state_map = {'OK': engine_api.WATCH_STATE_OK,
                      'ALARM': engine_api.WATCH_STATE_ALARM,
                      'INSUFFICIENT_DATA': engine_api.WATCH_STATE_NODATA}

        con = req.context
        parms = dict(req.params)

        # Get mandatory parameters
        name = api_utils.get_param_value(parms, 'AlarmName')
        state = api_utils.get_param_value(parms, 'StateValue')

        if state not in state_map:
            logger.error("Invalid state %s, expecting one of %s" %
                         (state, state_map.keys()))
            return exception.HeatInvalidParameterValueError("Invalid state %s"
                                                            % state)

        # Check for optional parameters
        # FIXME : We don't actually do anything with these in the engine yet..
        state_reason = None
        state_reason_data = None
        if 'StateReason' in parms:
            state_reason = parms['StateReason']
        if 'StateReasonData' in parms:
            state_reason_data = parms['StateReasonData']

        logger.debug("setting %s to %s" % (name, state_map[state]))
        try:
            ret = self.engine_rpcapi.set_watch_state(con, watch_name=name,
                                                       state=state_map[state])
        except rpc_common.RemoteError as ex:
            return exception.map_remote_error(ex)

        return api_utils.format_response("SetAlarmState", "")


def create_resource(options):
    """
    Watch resource factory method.
    """
    deserializer = wsgi.JSONRequestDeserializer()
    return wsgi.Resource(WatchController(options), deserializer)
