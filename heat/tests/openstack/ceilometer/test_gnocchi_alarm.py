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

import mock
import mox

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import ceilometer
from heat.engine.resources.openstack.ceilometer.gnocchi import (
    alarm as gnocchi)
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

gnocchi_resources_alarm_template = '''
heat_template_version: 2013-05-23
description: Gnocchi Resources Alarm Test
resources:
  GnoResAlarm:
    type: OS::Ceilometer::GnocchiResourcesAlarm
    properties:
      description: Do stuff with gnocchi
      metric: cpu_util
      aggregation_method: mean
      granularity: 60
      evaluation_periods: 1
      threshold: 50
      alarm_actions: []
      resource_type: instance
      resource_id: 5a517ceb-b068-4aca-9eb9-3e4eb9b90d9a
      comparison_operator: gt
'''


gnocchi_aggregation_by_metrics_alarm_template = '''
heat_template_version: 2013-05-23
description: Gnocchi Aggregation by Metrics Alarm Test
resources:
  GnoAggregationByMetricsAlarm:
    type: OS::Ceilometer::GnocchiAggregationByMetricsAlarm
    properties:
      description: Do stuff with gnocchi metrics
      metrics: ["911fce07-e0d7-4210-8c8c-4a9d811fcabc",
                "2543d435-fe93-4443-9351-fb0156930f94"]
      aggregation_method: mean
      granularity: 60
      evaluation_periods: 1
      threshold: 50
      alarm_actions: []
      comparison_operator: gt
'''

gnocchi_aggregation_by_resources_alarm_template = '''
heat_template_version: 2013-05-23
description: Gnocchi Aggregation by Resources Alarm Test
resources:
  GnoAggregationByResourcesAlarm:
    type: OS::Ceilometer::GnocchiAggregationByResourcesAlarm
    properties:
      description: Do stuff with gnocchi aggregation by resource
      aggregation_method: mean
      granularity: 60
      evaluation_periods: 1
      threshold: 50
      metric: cpu_util
      alarm_actions: []
      resource_type: instance
      query: '{"=": {"server_group": "my_autoscaling_group"}}'
      comparison_operator: gt
'''


class FakeCeilometerAlarm(object):
    alarm_id = 'foo'

    def __init__(self):
        self.to_dict = lambda: {'attr': 'val'}


class GnocchiResourcesAlarmTest(common.HeatTestCase):
    def setUp(self):
        super(GnocchiResourcesAlarmTest, self).setUp()
        self.fc = mock.Mock()

    def create_alarm(self):
        self.m.StubOutWithMock(ceilometer.CeilometerClientPlugin, '_create')
        ceilometer.CeilometerClientPlugin._create().AndReturn(
            self.fc)
        self.m.StubOutWithMock(self.fc.alarms, 'create')
        self.fc.alarms.create(
            alarm_actions=[],
            description=u'Do stuff with gnocchi',
            enabled=True,
            insufficient_data_actions=None,
            ok_actions=None,
            name=mox.IgnoreArg(), type='gnocchi_resources_threshold',
            repeat_actions=True,
            gnocchi_resources_threshold_rule={
                "metric": "cpu_util",
                "aggregation_method": "mean",
                "granularity": 60,
                "evaluation_periods": 1,
                "threshold": 50,
                "resource_type": "instance",
                "resource_id": "5a517ceb-b068-4aca-9eb9-3e4eb9b90d9a",
                "comparison_operator": "gt",
            },
            time_constraints=[],
            severity='low',
        ).AndReturn(FakeCeilometerAlarm())
        self.tmpl = template_format.parse(gnocchi_resources_alarm_template)
        self.stack = utils.parse_stack(self.tmpl)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return gnocchi.CeilometerGnocchiResourcesAlarm(
            'GnoResAlarm', resource_defns['GnoResAlarm'], self.stack)

    def test_update(self):
        rsrc = self.create_alarm()
        self.m.StubOutWithMock(self.fc.alarms, 'update')
        self.fc.alarms.update(
            alarm_id='foo',
            gnocchi_resources_threshold_rule={
                'resource_id': 'd3d6c642-921e-4fc2-9c5f-15d9a5afb598'})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        props = self.tmpl['resources']['GnoResAlarm']['properties']
        props['resource_id'] = 'd3d6c642-921e-4fc2-9c5f-15d9a5afb598'
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def _prepare_check_resource(self):
        snippet = template_format.parse(gnocchi_resources_alarm_template)
        self.stack = utils.parse_stack(snippet)
        res = self.stack['GnoResAlarm']
        res.client = mock.Mock()
        mock_alarm = mock.Mock(enabled=True, state='ok')
        res.client().alarms.get.return_value = mock_alarm
        return res

    def test_create(self):
        rsrc = self.create_alarm()

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('foo', rsrc.resource_id)
        self.m.VerifyAll()

    def test_suspend(self):
        rsrc = self.create_alarm()
        self.m.StubOutWithMock(self.fc.alarms, 'update')
        self.fc.alarms.update(alarm_id='foo', enabled=False)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_resume(self):
        rsrc = self.create_alarm()
        self.m.StubOutWithMock(self.fc.alarms, 'update')
        self.fc.alarms.update(alarm_id='foo', enabled=True)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        rsrc.state_set(rsrc.SUSPEND, rsrc.COMPLETE)

        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_check(self):
        res = self._prepare_check_resource()
        scheduler.TaskRunner(res.check)()
        self.assertEqual((res.CHECK, res.COMPLETE), res.state)

    def test_check_failure(self):
        res = self._prepare_check_resource()
        res.client().alarms.get.side_effect = Exception('Boom')

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(res.check))
        self.assertEqual((res.CHECK, res.FAILED), res.state)
        self.assertIn('Boom', res.status_reason)

    def test_show_resource(self):
        res = self._prepare_check_resource()
        res.client().alarms.create.return_value = mock.MagicMock(
            alarm_id='2')
        res.client().alarms.get.return_value = FakeCeilometerAlarm()
        scheduler.TaskRunner(res.create)()
        self.assertEqual({'attr': 'val'}, res.FnGetAtt('show'))


class GnocchiAggregationByMetricsAlarmTest(GnocchiResourcesAlarmTest):

    def create_alarm(self):
        self.m.StubOutWithMock(ceilometer.CeilometerClientPlugin, '_create')
        ceilometer.CeilometerClientPlugin._create().AndReturn(
            self.fc)
        self.m.StubOutWithMock(self.fc.alarms, 'create')
        self.fc.alarms.create(
            alarm_actions=[],
            description=u'Do stuff with gnocchi metrics',
            enabled=True,
            insufficient_data_actions=None,
            ok_actions=None,
            name=mox.IgnoreArg(),
            type='gnocchi_aggregation_by_metrics_threshold',
            repeat_actions=True,
            gnocchi_aggregation_by_metrics_threshold_rule={
                "aggregation_method": "mean",
                "granularity": 60,
                "evaluation_periods": 1,
                "threshold": 50,
                "comparison_operator": "gt",
                "metrics": ["911fce07-e0d7-4210-8c8c-4a9d811fcabc",
                            "2543d435-fe93-4443-9351-fb0156930f94"],
            },
            time_constraints=[],
            severity='low',
        ).AndReturn(FakeCeilometerAlarm())
        self.tmpl = template_format.parse(
            gnocchi_aggregation_by_metrics_alarm_template)
        self.stack = utils.parse_stack(self.tmpl)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return gnocchi.CeilometerGnocchiAggregationByMetricsAlarm(
            'GnoAggregationByMetricsAlarm',
            resource_defns['GnoAggregationByMetricsAlarm'], self.stack)

    def test_update(self):
        rsrc = self.create_alarm()
        self.m.StubOutWithMock(self.fc.alarms, 'update')
        self.fc.alarms.update(
            alarm_id='foo',
            gnocchi_aggregation_by_metrics_threshold_rule={
                'metrics': ['d3d6c642-921e-4fc2-9c5f-15d9a5afb598',
                            'bc60f822-18a0-4a0c-94e7-94c554b00901']})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        snippet = self.tmpl['resources']['GnoAggregationByMetricsAlarm']
        props = snippet['properties'].copy()
        props['metrics'] = ['d3d6c642-921e-4fc2-9c5f-15d9a5afb598',
                            'bc60f822-18a0-4a0c-94e7-94c554b00901']
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def _prepare_check_resource(self):
        snippet = template_format.parse(
            gnocchi_aggregation_by_metrics_alarm_template)
        self.stack = utils.parse_stack(snippet)
        res = self.stack['GnoAggregationByMetricsAlarm']
        res.client = mock.Mock()
        mock_alarm = mock.Mock(enabled=True, state='ok')
        res.client().alarms.get.return_value = mock_alarm
        return res

    def test_show_resource(self):
        res = self._prepare_check_resource()
        res.client().alarms.create.return_value = mock.MagicMock(
            alarm_id='2')
        res.client().alarms.get.return_value = FakeCeilometerAlarm()
        scheduler.TaskRunner(res.create)()
        self.assertEqual({'attr': 'val'}, res.FnGetAtt('show'))


class GnocchiAggregationByResourcesAlarmTest(GnocchiResourcesAlarmTest):

    def create_alarm(self):
        self.m.StubOutWithMock(ceilometer.CeilometerClientPlugin, '_create')
        ceilometer.CeilometerClientPlugin._create().AndReturn(
            self.fc)
        self.m.StubOutWithMock(self.fc.alarms, 'create')
        self.fc.alarms.create(
            alarm_actions=[],
            description=u'Do stuff with gnocchi aggregation by resource',
            enabled=True,
            insufficient_data_actions=None,
            ok_actions=None,
            name=mox.IgnoreArg(),
            type='gnocchi_aggregation_by_resources_threshold',
            repeat_actions=True,
            gnocchi_aggregation_by_resources_threshold_rule={
                "aggregation_method": "mean",
                "granularity": 60,
                "evaluation_periods": 1,
                "threshold": 50,
                "comparison_operator": "gt",
                "metric": "cpu_util",
                "resource_type": "instance",
                "query": '{"=": {"server_group": "my_autoscaling_group"}}',
            },
            time_constraints=[],
            severity='low',
        ).AndReturn(FakeCeilometerAlarm())
        self.tmpl = template_format.parse(
            gnocchi_aggregation_by_resources_alarm_template)
        self.stack = utils.parse_stack(self.tmpl)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return gnocchi.CeilometerGnocchiAggregationByResourcesAlarm(
            'GnoAggregationByResourcesAlarm',
            resource_defns['GnoAggregationByResourcesAlarm'], self.stack)

    def test_update(self):
        rsrc = self.create_alarm()
        self.m.StubOutWithMock(self.fc.alarms, 'update')
        self.fc.alarms.update(
            alarm_id='foo',
            gnocchi_aggregation_by_resources_threshold_rule={
                'query': '{"=": {"server_group": "my_new_group"}}'})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        snippet = self.tmpl['resources']['GnoAggregationByResourcesAlarm']
        props = snippet['properties'].copy()
        props['query'] = '{"=": {"server_group": "my_new_group"}}'
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def _prepare_check_resource(self):
        snippet = template_format.parse(
            gnocchi_aggregation_by_resources_alarm_template)
        self.stack = utils.parse_stack(snippet)
        res = self.stack['GnoAggregationByResourcesAlarm']
        res.client = mock.Mock()
        mock_alarm = mock.Mock(enabled=True, state='ok')
        res.client().alarms.get.return_value = mock_alarm
        return res

    def test_show_resource(self):
        res = self._prepare_check_resource()
        res.client().alarms.create.return_value = mock.MagicMock(
            alarm_id='2')
        res.client().alarms.get.return_value = FakeCeilometerAlarm()
        scheduler.TaskRunner(res.create)()
        self.assertEqual({'attr': 'val'}, res.FnGetAtt('show'))
