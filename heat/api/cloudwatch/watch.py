
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
from heat.common import exception as heat_exception
from heat.common import policy
from heat.common import wsgi
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging
from heat.openstack.common.rpc import common as rpc_common
from heat.rpc import api as engine_api
from heat.rpc import client as rpc_client

logger = logging.getLogger(__name__)


class WatchController(object):

    """
    WSGI controller for CloudWatch resource in heat API
    Implements the API actions
    """

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()
        self.policy = policy.Enforcer(scope='cloudwatch')

    def _enforce(self, req, action):
        """Authorize an action against the policy.json."""
        try:
            self.policy.enforce(req.context, action)
        except heat_exception.Forbidden:
            msg = _("Action %s not allowed for user") % action
            raise exception.HeatAccessDeniedError(msg)
        except Exception:
            # We expect policy.enforce to either pass or raise Forbidden
            # however, if anything else happens, we want to raise
            # HeatInternalFailureError, failure to do this results in
            # the user getting a big stacktrace spew as an API response
            msg = _("Error authorizing action %s") % action
            raise exception.HeatInternalFailureError(msg)

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
        self._enforce(req, 'DeleteAlarms')
        return exception.HeatAPINotImplementedError()

    def describe_alarm_history(self, req):
        """
        Implements DescribeAlarmHistory API action
        """
        self._enforce(req, 'DescribeAlarmHistory')
        return exception.HeatAPINotImplementedError()

    def describe_alarms(self, req):
        """
        Implements DescribeAlarms API action
        """
        self._enforce(req, 'DescribeAlarms')

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
                engine_api.WATCH_INSUFFICIENT_ACTIONS:
                'InsufficientDataActions',
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

            # AWS doesn't return StackId in the main MetricAlarm
            # structure, so we add StackId as a dimension to all responses
            a[engine_api.WATCH_DIMENSIONS].append({'StackId':
                                                  a[engine_api.WATCH_STACK_ID]
                                                   })

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
            watch_list = self.rpc_client.show_watch(con, watch_name=name)
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
        self._enforce(req, 'DescribeAlarmsForMetric')
        return exception.HeatAPINotImplementedError()

    def disable_alarm_actions(self, req):
        """
        Implements DisableAlarmActions API action
        """
        self._enforce(req, 'DisableAlarmActions')
        return exception.HeatAPINotImplementedError()

    def enable_alarm_actions(self, req):
        """
        Implements EnableAlarmActions API action
        """
        self._enforce(req, 'EnableAlarmActions')
        return exception.HeatAPINotImplementedError()

    def get_metric_statistics(self, req):
        """
        Implements GetMetricStatistics API action
        """
        self._enforce(req, 'GetMetricStatistics')
        return exception.HeatAPINotImplementedError()

    def list_metrics(self, req):
        """
        Implements ListMetrics API action
        Lists metric datapoints associated with a particular alarm,
        or all alarms if none specified
        """
        self._enforce(req, 'ListMetrics')

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
                    logger.warning(_("Invalid filter key %s, ignoring") % f)

            return result

        con = req.context
        parms = dict(req.params)
        # FIXME : Don't yet handle filtering by Dimensions
        filter_result = dict((k, v) for (k, v) in parms.iteritems() if k in
                             ("MetricName", "Namespace"))
        logger.debug(_("filter parameters : %s") % filter_result)

        try:
            # Engine does not currently support query by namespace/metric
            # so we pass None/None and do any filtering locally
            null_kwargs = {'metric_namespace': None,
                           'metric_name': None}
            watch_data = self.rpc_client.show_watch_metric(con,
                                                           **null_kwargs)
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
        self._enforce(req, 'PutMetricAlarm')
        return exception.HeatAPINotImplementedError()

    def put_metric_data(self, req):
        """
        Implements PutMetricData API action
        """
        self._enforce(req, 'PutMetricData')

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
            logger.error(_("Request does not contain required MetricData"))
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

        # Extract the required data from the metric_data
        # and format dict to pass to engine
        data = {'Namespace': namespace,
                api_utils.get_param_value(metric_data[0], 'MetricName'): {
                    'Unit': api_utils.get_param_value(metric_data[0], 'Unit'),
                    'Value': api_utils.get_param_value(metric_data[0],
                                                       'Value'),
                    'Dimensions': dimensions}}

        try:
            self.rpc_client.create_watch_data(con, watch_name, data)
        except rpc_common.RemoteError as ex:
            return exception.map_remote_error(ex)

        result = {'ResponseMetadata': None}
        return api_utils.format_response("PutMetricData", result)

    def set_alarm_state(self, req):
        """
        Implements SetAlarmState API action
        """
        self._enforce(req, 'SetAlarmState')

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
            msg = _('Invalid state %(state)s, '
                    'expecting one of %(expect)s') % {
                        'state': state,
                        'expect': state_map.keys()}
            logger.error(msg)
            return exception.HeatInvalidParameterValueError(msg)

        logger.debug(_("setting %(name)s to %(state)s") % {
                     'name': name, 'state': state_map[state]})
        try:
            self.rpc_client.set_watch_state(con, watch_name=name,
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
