
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

import os

from oslo.config import cfg

from heat.api.aws import exception
import heat.api.cloudwatch.watch as watches
from heat.common import policy
from heat.common.wsgi import Request
from heat.openstack.common import rpc
from heat.rpc import api as engine_api
from heat.tests.common import HeatTestCase
from heat.tests import utils


class WatchControllerTest(HeatTestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''

    def _dummy_GET_request(self, params={}):
        # Mangle the params dict into a query string
        qs = "&".join(["=".join([k, str(params[k])]) for k in params])
        environ = {'REQUEST_METHOD': 'GET', 'QUERY_STRING': qs}
        req = Request(environ)
        req.context = utils.dummy_context()
        return req

    # The tests
    def test_reformat_dimensions(self):

        dims = [{'StackId': u'21617058-781e-4262-97ab-5f9df371ee52',
                 'Foo': 'bar'}]
        self.assertEqual([{'Name': 'StackId',
                          'Value': u'21617058-781e-4262-97ab-5f9df371ee52'},
                          {'Name': 'Foo', 'Value': 'bar'}],
                         self.controller._reformat_dimensions(dims)
                         )

    def test_enforce_default(self):
        self.m.ReplayAll()
        params = {'Action': 'ListMetrics'}
        dummy_req = self._dummy_GET_request(params)
        self.controller.policy.policy_path = None
        response = self.controller._enforce(dummy_req, 'ListMetrics')
        self.assertIsNone(response)
        self.m.VerifyAll()

    def test_enforce_denied(self):
        self.m.ReplayAll()
        params = {'Action': 'ListMetrics'}
        dummy_req = self._dummy_GET_request(params)
        dummy_req.context.roles = ['heat_stack_user']
        self.controller.policy.policy_path = (self.policy_path +
                                              'deny_stack_user.json')
        self.assertRaises(exception.HeatAccessDeniedError,
                          self.controller._enforce, dummy_req, 'ListMetrics')
        self.m.VerifyAll()

    def test_enforce_ise(self):
        params = {'Action': 'ListMetrics'}
        dummy_req = self._dummy_GET_request(params)
        dummy_req.context.roles = ['heat_stack_user']

        self.m.StubOutWithMock(policy.Enforcer, 'enforce')
        policy.Enforcer.enforce(dummy_req.context, 'ListMetrics'
                                ).AndRaise(AttributeError)
        self.m.ReplayAll()

        self.controller.policy.policy_path = (self.policy_path +
                                              'deny_stack_user.json')
        self.assertRaises(exception.HeatInternalFailureError,
                          self.controller._enforce, dummy_req, 'ListMetrics')
        self.m.VerifyAll()

    def test_delete(self):
        # Not yet implemented, should raise HeatAPINotImplementedError
        params = {'Action': 'DeleteAlarms'}
        dummy_req = self._dummy_GET_request(params)
        result = self.controller.delete_alarms(dummy_req)
        self.assertIsInstance(result, exception.HeatAPINotImplementedError)

    def test_describe_alarm_history(self):
        # Not yet implemented, should raise HeatAPINotImplementedError
        params = {'Action': 'DescribeAlarmHistory'}
        dummy_req = self._dummy_GET_request(params)
        result = self.controller.describe_alarm_history(dummy_req)
        self.assertIsInstance(result, exception.HeatAPINotImplementedError)

    def test_describe_all(self):
        watch_name = None   # Get all watches

        # Format a dummy GET request to pass into the WSGI handler
        params = {'Action': 'DescribeAlarms'}
        dummy_req = self._dummy_GET_request(params)

        # Stub out the RPC call to the engine with a pre-canned response
        engine_resp = [{u'state_updated_time': u'2012-08-30T14:13:21Z',
                        u'stack_id': u'21617058-781e-4262-97ab-5f9df371ee52',
                        u'period': u'300',
                        u'actions': [u'WebServerRestartPolicy'],
                        u'topic': None,
                        u'periods': u'1',
                        u'statistic': u'SampleCount',
                        u'threshold': u'2',
                        u'unit': None,
                        u'state_reason': None,
                        u'dimensions': [],
                        u'namespace': u'system/linux',
                        u'state_value': u'NORMAL',
                        u'ok_actions': None,
                        u'description': u'Restart the WikiDatabase',
                        u'actions_enabled': None,
                        u'state_reason_data': None,
                        u'insufficient_actions': None,
                        u'metric_name': u'ServiceFailure',
                        u'comparison': u'GreaterThanThreshold',
                        u'name': u'HttpFailureAlarm',
                        u'updated_time': u'2012-08-30T14:10:46Z'}]

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(dummy_req.context, self.topic,
                 {'namespace': None,
                  'args': {'watch_name': watch_name},
                  'method': 'show_watch',
                  'version': self.api_version},
                 None).AndReturn(engine_resp)

        self.m.ReplayAll()

        expected = {'DescribeAlarmsResponse': {'DescribeAlarmsResult':
                    {'MetricAlarms': [
                        {'EvaluationPeriods': u'1',
                         'StateReasonData': None,
                         'AlarmArn': None,
                         'StateUpdatedTimestamp': u'2012-08-30T14:13:21Z',
                         'AlarmConfigurationUpdatedTimestamp':
                         u'2012-08-30T14:10:46Z',
                         'AlarmActions': [u'WebServerRestartPolicy'],
                         'Threshold': u'2',
                         'AlarmDescription': u'Restart the WikiDatabase',
                         'Namespace': u'system/linux',
                         'Period': u'300',
                         'StateValue': u'NORMAL',
                         'ComparisonOperator': u'GreaterThanThreshold',
                         'AlarmName': u'HttpFailureAlarm',
                         'Unit': None,
                         'Statistic': u'SampleCount',
                         'StateReason': None,
                         'InsufficientDataActions': None,
                         'OKActions': None,
                         'MetricName': u'ServiceFailure',
                         'ActionsEnabled': None,
                         'Dimensions':
                         [{'Name': 'StackId',
                           'Value': u'21617058-781e-4262-97ab-5f9df371ee52'}]
                         }]}}}

        # Call the list controller function and compare the response
        self.assertEqual(expected, self.controller.describe_alarms(dummy_req))

    def test_describe_alarms_for_metric(self):
        # Not yet implemented, should raise HeatAPINotImplementedError
        params = {'Action': 'DescribeAlarmsForMetric'}
        dummy_req = self._dummy_GET_request(params)
        result = self.controller.describe_alarms_for_metric(dummy_req)
        self.assertIsInstance(result, exception.HeatAPINotImplementedError)

    def test_disable_alarm_actions(self):
        # Not yet implemented, should raise HeatAPINotImplementedError
        params = {'Action': 'DisableAlarmActions'}
        dummy_req = self._dummy_GET_request(params)
        result = self.controller.disable_alarm_actions(dummy_req)
        self.assertIsInstance(result, exception.HeatAPINotImplementedError)

    def test_enable_alarm_actions(self):
        # Not yet implemented, should raise HeatAPINotImplementedError
        params = {'Action': 'EnableAlarmActions'}
        dummy_req = self._dummy_GET_request(params)
        result = self.controller.enable_alarm_actions(dummy_req)
        self.assertIsInstance(result, exception.HeatAPINotImplementedError)

    def test_get_metric_statistics(self):
        # Not yet implemented, should raise HeatAPINotImplementedError
        params = {'Action': 'GetMetricStatistics'}
        dummy_req = self._dummy_GET_request(params)
        result = self.controller.get_metric_statistics(dummy_req)
        self.assertIsInstance(result, exception.HeatAPINotImplementedError)

    def test_list_metrics_all(self):
        params = {'Action': 'ListMetrics'}
        dummy_req = self._dummy_GET_request(params)

        # Stub out the RPC call to the engine with a pre-canned response
        # We dummy three different metrics and namespaces to test
        # filtering by parameter
        engine_resp = [{u'timestamp': u'2012-08-30T15:09:02Z',
                        u'watch_name': u'HttpFailureAlarm',
                        u'namespace': u'system/linux',
                        u'metric_name': u'ServiceFailure',
                        u'data': {u'Units': u'Counter', u'Value': 1}},

                       {u'timestamp': u'2012-08-30T15:10:03Z',
                        u'watch_name': u'HttpFailureAlarm2',
                        u'namespace': u'system/linux2',
                        u'metric_name': u'ServiceFailure2',
                        u'data': {u'Units': u'Counter', u'Value': 1}},

                       {u'timestamp': u'2012-08-30T15:16:03Z',
                        u'watch_name': u'HttpFailureAlar3m',
                        u'namespace': u'system/linux3',
                        u'metric_name': u'ServiceFailure3',
                        u'data': {u'Units': u'Counter', u'Value': 1}}]

        self.m.StubOutWithMock(rpc, 'call')
        # Current engine implementation means we filter in the API
        # and pass None/None for namespace/watch_name which returns
        # all metric data which we post-process in the API
        rpc.call(dummy_req.context, self.topic,
                 {'namespace': None,
                  'args': {'metric_namespace': None, 'metric_name': None},
                  'method': 'show_watch_metric',
                  'version': self.api_version},
                 None).AndReturn(engine_resp)

        self.m.ReplayAll()

        expected = {'ListMetricsResponse':
                    {'ListMetricsResult':
                     {'Metrics': [{'Namespace': u'system/linux',
                                   'Dimensions':
                                   [{'Name': 'AlarmName',
                                     'Value': u'HttpFailureAlarm'},
                                    {'Name': 'Timestamp',
                                     'Value': u'2012-08-30T15:09:02Z'},
                                    {'Name': u'Units',
                                     'Value': u'Counter'},
                                    {'Name': u'Value',
                                     'Value': 1}],
                                   'MetricName': u'ServiceFailure'},
                                  {'Namespace': u'system/linux2',
                                   'Dimensions':
                                   [{'Name': 'AlarmName',
                                     'Value': u'HttpFailureAlarm2'},
                                    {'Name': 'Timestamp',
                                     'Value': u'2012-08-30T15:10:03Z'},
                                    {'Name': u'Units',
                                     'Value': u'Counter'},
                                    {'Name': u'Value',
                                     'Value': 1}],
                                   'MetricName': u'ServiceFailure2'},
                                  {'Namespace': u'system/linux3',
                                   'Dimensions':
                                   [{'Name': 'AlarmName',
                                     'Value': u'HttpFailureAlar3m'},
                                    {'Name': 'Timestamp',
                                     'Value': u'2012-08-30T15:16:03Z'},
                                    {'Name': u'Units',
                                     'Value': u'Counter'},
                                    {'Name': u'Value',
                                     'Value': 1}],
                                   'MetricName': u'ServiceFailure3'}]}}}

        # First pass no query paramters filtering, should get all three
        self.assertEqual(expected, self.controller.list_metrics(dummy_req))

    def test_list_metrics_filter_name(self):

        # Add a MetricName filter, so we should only get one of the three
        params = {'Action': 'ListMetrics',
                  'MetricName': 'ServiceFailure'}
        dummy_req = self._dummy_GET_request(params)

        # Stub out the RPC call to the engine with a pre-canned response
        # We dummy three different metrics and namespaces to test
        # filtering by parameter
        engine_resp = [{u'timestamp': u'2012-08-30T15:09:02Z',
                        u'watch_name': u'HttpFailureAlarm',
                        u'namespace': u'system/linux',
                        u'metric_name': u'ServiceFailure',
                        u'data': {u'Units': u'Counter', u'Value': 1}},

                       {u'timestamp': u'2012-08-30T15:10:03Z',
                        u'watch_name': u'HttpFailureAlarm2',
                        u'namespace': u'system/linux2',
                        u'metric_name': u'ServiceFailure2',
                        u'data': {u'Units': u'Counter', u'Value': 1}},

                       {u'timestamp': u'2012-08-30T15:16:03Z',
                        u'watch_name': u'HttpFailureAlar3m',
                        u'namespace': u'system/linux3',
                        u'metric_name': u'ServiceFailure3',
                        u'data': {u'Units': u'Counter', u'Value': 1}}]

        self.m.StubOutWithMock(rpc, 'call')
        # Current engine implementation means we filter in the API
        # and pass None/None for namespace/watch_name which returns
        # all metric data which we post-process in the API
        rpc.call(dummy_req.context, self.topic, {'args':
                 {'metric_namespace': None,
                  'metric_name': None},
                 'namespace': None,
                 'method': 'show_watch_metric',
                 'version': self.api_version},
                 None).AndReturn(engine_resp)

        self.m.ReplayAll()

        expected = {'ListMetricsResponse':
                    {'ListMetricsResult':
                     {'Metrics':
                      [{'Namespace': u'system/linux',
                        'Dimensions':
                        [{'Name': 'AlarmName',
                          'Value': u'HttpFailureAlarm'},
                         {'Name': 'Timestamp',
                          'Value': u'2012-08-30T15:09:02Z'},
                         {'Name': u'Units',
                          'Value': u'Counter'},
                         {'Name': u'Value',
                          'Value': 1}],
                        'MetricName': u'ServiceFailure'}]}}}
        # First pass no query paramters filtering, should get all three
        self.assertEqual(expected, self.controller.list_metrics(dummy_req))

    def test_list_metrics_filter_namespace(self):

        # Add a Namespace filter and change the engine response so
        # we should get two reponses
        params = {'Action': 'ListMetrics',
                  'Namespace': 'atestnamespace/foo'}
        dummy_req = self._dummy_GET_request(params)

        # Stub out the RPC call to the engine with a pre-canned response
        # We dummy three different metrics and namespaces to test
        # filtering by parameter
        engine_resp = [{u'timestamp': u'2012-08-30T15:09:02Z',
                        u'watch_name': u'HttpFailureAlarm',
                        u'namespace': u'atestnamespace/foo',
                        u'metric_name': u'ServiceFailure',
                        u'data': {u'Units': u'Counter', u'Value': 1}},

                       {u'timestamp': u'2012-08-30T15:10:03Z',
                        u'watch_name': u'HttpFailureAlarm2',
                        u'namespace': u'atestnamespace/foo',
                        u'metric_name': u'ServiceFailure2',
                        u'data': {u'Units': u'Counter', u'Value': 1}},

                       {u'timestamp': u'2012-08-30T15:16:03Z',
                        u'watch_name': u'HttpFailureAlar3m',
                        u'namespace': u'system/linux3',
                        u'metric_name': u'ServiceFailure3',
                        u'data': {u'Units': u'Counter', u'Value': 1}}]

        self.m.StubOutWithMock(rpc, 'call')
        # Current engine implementation means we filter in the API
        # and pass None/None for namespace/watch_name which returns
        # all metric data which we post-process in the API
        rpc.call(dummy_req.context, self.topic,
                 {'args': {'metric_namespace': None, 'metric_name': None},
                  'namespace': None,
                  'method': 'show_watch_metric',
                  'version': self.api_version},
                 None).AndReturn(engine_resp)

        self.m.ReplayAll()

        expected = {'ListMetricsResponse':
                    {'ListMetricsResult':
                     {'Metrics':
                      [{'Namespace': u'atestnamespace/foo',
                        'Dimensions':
                        [{'Name': 'AlarmName',
                          'Value': u'HttpFailureAlarm'},
                         {'Name': 'Timestamp',
                          'Value': u'2012-08-30T15:09:02Z'},
                         {'Name': u'Units',
                          'Value': u'Counter'},
                         {'Name': u'Value',
                          'Value': 1}],
                        'MetricName': u'ServiceFailure'},
                       {'Namespace': u'atestnamespace/foo',
                        'Dimensions':
                        [{'Name': 'AlarmName',
                          'Value': u'HttpFailureAlarm2'},
                         {'Name': 'Timestamp',
                          'Value': u'2012-08-30T15:10:03Z'},
                         {'Name': u'Units',
                          'Value': u'Counter'},
                         {'Name': u'Value',
                          'Value': 1}],
                        'MetricName': u'ServiceFailure2'}]}}}
        self.assertEqual(expected, self.controller.list_metrics(dummy_req))

    def test_put_metric_alarm(self):
        # Not yet implemented, should raise HeatAPINotImplementedError
        params = {'Action': 'PutMetricAlarm'}
        dummy_req = self._dummy_GET_request(params)
        result = self.controller.put_metric_alarm(dummy_req)
        self.assertIsInstance(result, exception.HeatAPINotImplementedError)

    def test_put_metric_data(self):

        params = {u'Namespace': u'system/linux',
                  u'MetricData.member.1.Unit': u'Count',
                  u'MetricData.member.1.Value': u'1',
                  u'MetricData.member.1.MetricName': u'ServiceFailure',
                  u'MetricData.member.1.Dimensions.member.1.Name':
                  u'AlarmName',
                  u'MetricData.member.1.Dimensions.member.1.Value':
                  u'HttpFailureAlarm',
                  u'Action': u'PutMetricData'}

        dummy_req = self._dummy_GET_request(params)

        # Stub out the RPC call to verify the engine call parameters
        engine_resp = {}

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(dummy_req.context, self.topic,
                 {'args':
                  {'stats_data':
                      {'Namespace': u'system/linux',
                       u'ServiceFailure':
                       {'Value': u'1',
                        'Unit': u'Count',
                        'Dimensions': []}},
                   'watch_name': u'HttpFailureAlarm'},
                  'namespace': None,
                  'method': 'create_watch_data',
                  'version': self.api_version},
                 None).AndReturn(engine_resp)

        self.m.ReplayAll()

        expected = {'PutMetricDataResponse': {'PutMetricDataResult':
                    {'ResponseMetadata': None}}}
        self.assertEqual(expected, self.controller.put_metric_data(dummy_req))

    def test_set_alarm_state(self):
        state_map = {'OK': engine_api.WATCH_STATE_OK,
                     'ALARM': engine_api.WATCH_STATE_ALARM,
                     'INSUFFICIENT_DATA': engine_api.WATCH_STATE_NODATA}

        for state in state_map.keys():
            params = {u'StateValue': state,
                      u'StateReason': u'',
                      u'AlarmName': u'HttpFailureAlarm',
                      u'Action': u'SetAlarmState'}

            dummy_req = self._dummy_GET_request(params)

            # Stub out the RPC call to verify the engine call parameters
            # The real engine response is the same as show_watch but with
            # the state overridden, but since the API doesn't make use
            # of the response at present we pass nothing back from the stub
            engine_resp = {}

            self.m.StubOutWithMock(rpc, 'call')
            rpc.call(dummy_req.context, self.topic,
                     {'args':
                      {'state': state_map[state],
                       'watch_name': u'HttpFailureAlarm'},
                      'namespace': None,
                      'method': 'set_watch_state',
                      'version': self.api_version},
                     None).AndReturn(engine_resp)

            self.m.ReplayAll()

            expected = {'SetAlarmStateResponse': {'SetAlarmStateResult': ''}}
            self.assertEqual(expected,
                             self.controller.set_alarm_state(dummy_req))

            self.m.UnsetStubs()
            self.m.VerifyAll()

    def test_set_alarm_state_badstate(self):
        params = {u'StateValue': "baaaaad",
                  u'StateReason': u'',
                  u'AlarmName': u'HttpFailureAlarm',
                  u'Action': u'SetAlarmState'}
        dummy_req = self._dummy_GET_request(params)

        # should raise HeatInvalidParameterValueError
        result = self.controller.set_alarm_state(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def setUp(self):
        super(WatchControllerTest, self).setUp()
        self.path = os.path.dirname(os.path.realpath(__file__))
        self.policy_path = self.path + "/policy/"
        opts = [
            cfg.StrOpt('config_dir', default=self.policy_path),
            cfg.StrOpt('config_file', default='foo'),
            cfg.StrOpt('project', default='heat'),
        ]
        cfg.CONF.register_opts(opts)
        cfg.CONF.set_default('host', 'host')
        self.topic = engine_api.ENGINE_TOPIC
        self.api_version = '1.0'

        # Create WSGI controller instance
        class DummyConfig():
            bind_port = 8003
        cfgopts = DummyConfig()
        self.controller = watches.WatchController(options=cfgopts)
        self.controller.policy.enforcer.policy_path = (self.policy_path +
                                                       'deny_stack_user.json')
        self.addCleanup(self.m.VerifyAll)
