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

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.openstack.mistral import cron_trigger
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

stack_template = '''
heat_template_version: 2013-05-23

resources:
  cron_trigger:
    type: OS::Mistral::CronTrigger
    properties:
      name: my_cron_trigger
      pattern: "* * 0 * *"
      workflow: {'name': 'get_first_glance_image', 'input': {} }
      count: 3
      first_time: "2015-04-08 06:20"
'''


class FakeCronTrigger(object):

    def __init__(self, name):
        self.name = name
        self.next_execution_time = '2015-03-01 00:00:00'
        self.remaining_executions = 3
        self._data = {'trigger': 'info'}

    def to_dict(self):
        return self._data


class MistralCronTriggerTest(common.HeatTestCase):

    def setUp(self):
        super(MistralCronTriggerTest, self).setUp()

        t = template_format.parse(stack_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['cron_trigger']

        self.client = mock.Mock()
        self.patchobject(cron_trigger.CronTrigger, 'client',
                         return_value=self.client)

    def _create_resource(self, name, snippet, stack):
        ct = cron_trigger.CronTrigger(name, snippet, stack)
        mock_get_workflow = mock.Mock(return_value='get_first_glance_image')
        ct.client_plugin().get_workflow_by_identifier = mock_get_workflow
        self.client.cron_triggers.create.return_value = FakeCronTrigger(
            'my_cron_trigger')
        self.client.cron_triggers.get.return_value = FakeCronTrigger(
            'my_cron_trigger')
        scheduler.TaskRunner(ct.create)()
        return ct

    def test_create(self):
        ct = self._create_resource('trigger', self.rsrc_defn, self.stack)
        expected_state = (ct.CREATE, ct.COMPLETE)
        self.assertEqual(expected_state, ct.state)
        args, kwargs = self.client.cron_triggers.create.call_args
        self.assertEqual('* * 0 * *', kwargs['pattern'])
        self.assertEqual('get_first_glance_image', args[1])
        self.assertEqual({}, kwargs['workflow_input'])
        self.assertEqual('2015-04-08 06:20', kwargs['first_time'])
        self.assertEqual(3, kwargs['count'])
        self.assertEqual('my_cron_trigger', ct.resource_id)

    def test_attributes(self):
        ct = self._create_resource('trigger', self.rsrc_defn, self.stack)
        self.assertEqual('2015-03-01 00:00:00',
                         ct.FnGetAtt('next_execution_time'))
        self.assertEqual(3, ct.FnGetAtt('remaining_executions'))
        self.assertEqual({'trigger': 'info'}, ct.FnGetAtt('show'))

    def test_validate_fail(self):
        t = template_format.parse(stack_template)
        del t['resources']['cron_trigger']['properties']['first_time']
        del t['resources']['cron_trigger']['properties']['pattern']
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        self.rsrc_defn = resource_defns['cron_trigger']
        ct = self._create_resource('trigger', self.rsrc_defn, self.stack)
        msg = ("At least one of the following properties must be specified: "
               "pattern, first_time")
        self.assertRaisesRegex(exception.PropertyUnspecifiedError, msg,
                               ct.validate)

    def test_validate_ok_without_first_time(self):
        t = template_format.parse(stack_template)
        del t['resources']['cron_trigger']['properties']['first_time']
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        self.rsrc_defn = resource_defns['cron_trigger']
        ct = self._create_resource('trigger', self.rsrc_defn, self.stack)
        ct.validate()

    def test_validate_ok_without_pattern(self):
        t = template_format.parse(stack_template)
        del t['resources']['cron_trigger']['properties']['pattern']
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        self.rsrc_defn = resource_defns['cron_trigger']
        ct = self._create_resource('trigger', self.rsrc_defn, self.stack)
        ct.validate()
