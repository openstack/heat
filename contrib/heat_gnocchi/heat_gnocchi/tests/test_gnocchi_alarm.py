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

import copy

from ceilometerclient import exc as ceilometerclient_exc
import mock
import mox
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import ceilometer
from heat.engine import resource
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

from ..resources import gnocchi_alarm as gnocchi  # noqa

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
      resource_constraint: server_group=mystack
      comparison_operator: gt
'''


gnocchi_metrics_alarm_template = '''
heat_template_version: 2013-05-23
description: Gnocchi Metrics Alarm Test
resources:
  GnoMetricsAlarm:
    type: OS::Ceilometer::GnocchiMetricsAlarm
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


class FakeCeilometerAlarm(object):
    alarm_id = 'foo'


class GnocchiResourcesAlarmTest(common.HeatTestCase):
    def setUp(self):
        super(GnocchiResourcesAlarmTest, self).setUp()
        self.fc = mock.Mock()
        self._register_resources()

    def _register_resources(self):
        for res_name, res_class in six.iteritems(gnocchi.resource_mapping()):
            resource._register_class(res_name, res_class)

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
                "resource_constraint": "server_group=mystack",
                "comparison_operator": "gt",
            }
        ).AndReturn(FakeCeilometerAlarm())
        snippet = template_format.parse(gnocchi_resources_alarm_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        return gnocchi.CeilometerGnocchiResourcesAlarm(
            'GnoResAlarm', resource_defns['GnoResAlarm'], stack)

    def test_update(self):
        rsrc = self.create_alarm()
        self.m.StubOutWithMock(self.fc.alarms, 'update')
        self.fc.alarms.update(
            alarm_id='foo',
            gnocchi_resources_threshold_rule={
                'resource_constraint': 'd3d6c642-921e-4fc2-9c5f-15d9a5afb598'})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['resource_constraint'] = (
            'd3d6c642-921e-4fc2-9c5f-15d9a5afb598')
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def _prepare_check_resource(self):
        snippet = template_format.parse(gnocchi_resources_alarm_template)
        stack = utils.parse_stack(snippet)
        res = stack['GnoResAlarm']
        res.ceilometer = mock.Mock()
        mock_alarm = mock.Mock(enabled=True, state='ok')
        res.ceilometer().alarms.get.return_value = mock_alarm
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

    def test_delete(self):
        rsrc = self.create_alarm()
        self.m.StubOutWithMock(self.fc.alarms, 'delete')
        self.fc.alarms.delete('foo')
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_delete_not_found(self):
        rsrc = self.create_alarm()
        self.m.StubOutWithMock(self.fc.alarms, 'delete')
        self.fc.alarms.delete('foo').AndRaise(
            ceilometerclient_exc.HTTPNotFound())
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_check(self):
        res = self._prepare_check_resource()
        scheduler.TaskRunner(res.check)()
        self.assertEqual((res.CHECK, res.COMPLETE), res.state)

    def test_check_failure(self):
        res = self._prepare_check_resource()
        res.ceilometer().alarms.get.side_effect = Exception('Boom')

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(res.check))
        self.assertEqual((res.CHECK, res.FAILED), res.state)
        self.assertIn('Boom', res.status_reason)


class GnocchiMetricsAlarmTest(GnocchiResourcesAlarmTest):

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
            name=mox.IgnoreArg(), type='gnocchi_metrics_threshold',
            repeat_actions=True,
            gnocchi_metrics_threshold_rule={
                "aggregation_method": "mean",
                "granularity": 60,
                "evaluation_periods": 1,
                "threshold": 50,
                "comparison_operator": "gt",
                "metrics": ["911fce07-e0d7-4210-8c8c-4a9d811fcabc",
                            "2543d435-fe93-4443-9351-fb0156930f94"],
            }
        ).AndReturn(FakeCeilometerAlarm())
        snippet = template_format.parse(gnocchi_metrics_alarm_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        return gnocchi.CeilometerGnocchiMetricsAlarm(
            'GnoMetricsAlarm', resource_defns['GnoMetricsAlarm'], stack)

    def test_update(self):
        rsrc = self.create_alarm()
        self.m.StubOutWithMock(self.fc.alarms, 'update')
        self.fc.alarms.update(
            alarm_id='foo',
            gnocchi_metrics_threshold_rule={
                'metrics': ['d3d6c642-921e-4fc2-9c5f-15d9a5afb598',
                            'bc60f822-18a0-4a0c-94e7-94c554b00901']})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['metrics'] = [
            'd3d6c642-921e-4fc2-9c5f-15d9a5afb598',
            'bc60f822-18a0-4a0c-94e7-94c554b00901']
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def _prepare_check_resource(self):
        snippet = template_format.parse(gnocchi_metrics_alarm_template)
        stack = utils.parse_stack(snippet)
        res = stack['GnoMetricsAlarm']
        res.ceilometer = mock.Mock()
        mock_alarm = mock.Mock(enabled=True, state='ok')
        res.ceilometer().alarms.get.return_value = mock_alarm
        return res
