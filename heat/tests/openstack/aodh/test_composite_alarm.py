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

import mock
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import aodh
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template as tmpl
from heat.tests import common
from heat.tests import utils


alarm_template = '''
heat_template_version: 2016-10-14
resources:
  cps_alarm:
    type: OS::Aodh::CompositeAlarm
    properties:
      description: test the composite alarm
      alarm_actions: []
      severity: moderate
      composite_rule:
        operator: or
        rules:
        - type: threshold
          meter_name: cpu_util
          evaluation_periods: 1
          period: 60
          statistic: avg
          threshold: 0.8
          comparison_operator: ge
          exclude_outliers: false
        - and:
          - type: threshold
            meter_name: disk.usage
            evaluation_periods: 1
            period: 60
            statistic: avg
            threshold: 0.8
            comparison_operator: ge
            exclude_outliers: false
          - type: threshold
            meter_name: mem_util
            evaluation_periods: 1
            period: 60
            statistic: avg
            threshold: 0.8
            comparison_operator: ge
            exclude_outliers: false
'''


FakeCompositeAlarm = {'other_attrs': 'val',
                      'alarm_id': 'foo'}


class CompositeAlarmTest(common.HeatTestCase):
    def setUp(self):
        super(CompositeAlarmTest, self).setUp()
        self.fa = mock.Mock()

    def create_stack(self, template=None):
        temp = template_format.parse(template)
        template = tmpl.Template(temp)
        ctx = utils.dummy_context()
        ctx.tenant = 'test_tenant'
        stack = parser.Stack(ctx, utils.random_name(), template,
                             disable_rollback=True)
        stack.store()

        self.patchobject(aodh.AodhClientPlugin,
                         '_create').return_value = self.fa

        self.patchobject(self.fa.alarm,
                         'create').return_value = FakeCompositeAlarm

        return stack

    def test_handle_create(self):
        """Test create the composite alarm."""

        test_stack = self.create_stack(template=alarm_template)
        test_stack.create()
        rsrc = test_stack['cps_alarm']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

    def test_handle_update(self):
        """Test update the composite alarm."""

        test_stack = self.create_stack(template=alarm_template)
        update_mock = self.patchobject(self.fa.alarm, 'update')

        test_stack.create()
        rsrc = test_stack['cps_alarm']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        after_props = copy.deepcopy(rsrc.properties.data)
        update_props = {
            'enabled': False,
            'repeat_actions': False,
            'insufficient_data_actions': [],
            'ok_actions': ['signal_handler']
        }
        after_props.update(update_props)

        snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                               rsrc.type(),
                                               after_props)

        scheduler.TaskRunner(rsrc.update, snippet)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(1, update_mock.call_count)

    def test_validate(self):
        test_stack = self.create_stack(template=alarm_template)
        props = test_stack.t['resources']['cps_alarm']['Properties']
        props['composite_rule']['operator'] = 'invalid'
        res = test_stack['cps_alarm']
        error_msg = '"invalid" is not an allowed value [or, and]'

        exc = self.assertRaises(exception.StackValidationFailed,
                                res.validate)
        self.assertIn(error_msg, six.text_type(exc))

    def test_show_resource(self):
        test_stack = self.create_stack(template=alarm_template)
        res = test_stack['cps_alarm']
        res.client().alarm.create.return_value = FakeCompositeAlarm
        res.client().alarm.get.return_value = FakeCompositeAlarm
        scheduler.TaskRunner(res.create)()
        self.assertEqual(FakeCompositeAlarm, res.FnGetAtt('show'))
