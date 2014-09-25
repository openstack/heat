
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
import json

import mox
from oslo.config import cfg
import testtools

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine import parser
from heat.engine.properties import schemata
from heat.engine import resource
from heat.engine.resources.ceilometer import alarm
from heat.engine import scheduler
from heat.engine import stack_user
from heat.openstack.common.importutils import try_import
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import generic_resource
from heat.tests import utils

ceilometerclient = try_import('ceilometerclient.v2')

alarm_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Alarm Test",
  "Parameters" : {},
  "Resources" : {
    "MEMAlarmHigh": {
     "Type": "OS::Ceilometer::Alarm",
     "Properties": {
        "description": "Scale-up if MEM > 50% for 1 minute",
        "meter_name": "MemoryUtilization",
        "statistic": "avg",
        "period": "60",
        "evaluation_periods": "1",
        "threshold": "50",
        "alarm_actions": [],
        "matching_metadata": {},
        "comparison_operator": "gt"
      }
    },
    "signal_handler" : {
      "Type" : "SignalResourceType"
    }
  }
}
'''

not_string_alarm_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Alarm Test",
  "Parameters" : {},
  "Resources" : {
    "MEMAlarmHigh": {
     "Type": "OS::Ceilometer::Alarm",
     "Properties": {
        "description": "Scale-up if MEM > 50% for 1 minute",
        "meter_name": "MemoryUtilization",
        "statistic": "avg",
        "period": 60,
        "evaluation_periods": 1,
        "threshold": 50,
        "alarm_actions": [],
        "matching_metadata": {},
        "comparison_operator": "gt"
      }
    },
    "signal_handler" : {
      "Type" : "SignalResourceType"
    }
  }
}
'''

combination_alarm_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Combination Alarm Test",
  "Resources" : {
    "CombinAlarm": {
     "Type": "OS::Ceilometer::CombinationAlarm",
     "Properties": {
        "description": "Do stuff in combination",
        "alarm_ids": ["alarm1", "alarm2"],
        "operator": "and",
        "alarm_actions": [],
      }
    }
  }
}
'''


class FakeCeilometerAlarm(object):
    alarm_id = 'foo'


class FakeCeilometerAlarms(object):
    def create(self, **kwargs):
        pass

    def update(self, **kwargs):
        pass

    def delete(self, alarm_id):
        pass


class FakeCeilometerClient(object):
    alarms = FakeCeilometerAlarms()


@testtools.skipIf(ceilometerclient is None, 'ceilometerclient unavailable')
class CeilometerAlarmTest(HeatTestCase):
    def setUp(self):
        super(CeilometerAlarmTest, self).setUp()
        utils.setup_dummy_db()

        resource._register_class('SignalResourceType',
                                 generic_resource.SignalResource)

        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')

        self.fc = fakes.FakeKeystoneClient()
        self.fa = FakeCeilometerClient()

    # Note tests creating a stack should be decorated with @stack_delete_after
    # to ensure the stack is properly cleaned up
    def create_stack(self, template=None):
        if template is None:
            template = alarm_template
        temp = template_format.parse(template)
        template = parser.Template(temp)
        ctx = utils.dummy_context()
        ctx.tenant_id = 'test_tenant'
        stack = parser.Stack(ctx, utils.random_name(), template,
                             disable_rollback=True)
        stack.store()

        self.m.StubOutWithMock(stack_user.StackUser, 'keystone')
        stack_user.StackUser.keystone().MultipleTimes().AndReturn(
            self.fc)

        self.m.StubOutWithMock(alarm.CeilometerAlarm, 'ceilometer')
        alarm.CeilometerAlarm.ceilometer().MultipleTimes().AndReturn(
            self.fa)

        al = copy.deepcopy(temp['Resources']['MEMAlarmHigh']['Properties'])
        al['description'] = mox.IgnoreArg()
        al['name'] = mox.IgnoreArg()
        al['alarm_actions'] = mox.IgnoreArg()
        self.m.StubOutWithMock(self.fa.alarms, 'create')
        self.fa.alarms.create(**al).AndReturn(FakeCeilometerAlarm())
        return stack

    @utils.stack_delete_after
    def test_mem_alarm_high_update_no_replace(self):
        '''
        Make sure that we can change the update-able properties
        without replacing the Alarm rsrc.
        '''
        #short circuit the alarm's references
        t = template_format.parse(alarm_template)
        properties = t['Resources']['MEMAlarmHigh']['Properties']
        properties['alarm_actions'] = ['signal_handler']
        properties['matching_metadata'] = {'a': 'v'}

        self.stack = self.create_stack(template=json.dumps(t))
        self.m.StubOutWithMock(self.fa.alarms, 'update')
        schema = schemata(alarm.CeilometerAlarm.properties_schema)
        al2 = dict((k, mox.IgnoreArg())
                   for k, s in schema.items() if s.update_allowed)
        al2['alarm_id'] = mox.IgnoreArg()
        self.fa.alarms.update(**al2).AndReturn(None)

        self.m.ReplayAll()
        self.stack.create()
        rsrc = self.stack['MEMAlarmHigh']

        snippet = copy.deepcopy(rsrc.parsed_template())
        snippet['Properties']['comparison_operator'] = 'lt'
        snippet['Properties']['description'] = 'fruity'
        snippet['Properties']['evaluation_periods'] = '2'
        snippet['Properties']['period'] = '90'
        snippet['Properties']['enabled'] = 'true'
        snippet['Properties']['repeat_actions'] = True
        snippet['Properties']['statistic'] = 'max'
        snippet['Properties']['threshold'] = '39'
        snippet['Properties']['insufficient_data_actions'] = []
        snippet['Properties']['alarm_actions'] = []
        snippet['Properties']['ok_actions'] = ['signal_handler']

        scheduler.TaskRunner(rsrc.update, snippet)()

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_mem_alarm_high_update_replace(self):
        '''
        Make sure that the Alarm resource IS replaced when non-update-able
        properties are changed.
        '''
        t = template_format.parse(alarm_template)
        properties = t['Resources']['MEMAlarmHigh']['Properties']
        properties['alarm_actions'] = ['signal_handler']
        properties['matching_metadata'] = {'a': 'v'}

        self.stack = self.create_stack(template=json.dumps(t))

        self.m.ReplayAll()
        self.stack.create()
        rsrc = self.stack['MEMAlarmHigh']

        snippet = copy.deepcopy(rsrc.parsed_template())
        snippet['Properties']['meter_name'] = 'temp'

        updater = scheduler.TaskRunner(rsrc.update, snippet)
        self.assertRaises(resource.UpdateReplace, updater)

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_mem_alarm_suspend_resume(self):
        """
        Make sure that the Alarm resource gets disabled on suspend
        and reenabled on resume.
        """
        self.stack = self.create_stack()

        self.m.StubOutWithMock(self.fa.alarms, 'update')
        al_suspend = {'alarm_id': mox.IgnoreArg(),
                      'enabled': False}
        self.fa.alarms.update(**al_suspend).AndReturn(None)
        al_resume = {'alarm_id': mox.IgnoreArg(),
                     'enabled': True}
        self.fa.alarms.update(**al_resume).AndReturn(None)
        self.m.ReplayAll()

        self.stack.create()
        rsrc = self.stack['MEMAlarmHigh']
        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_mem_alarm_high_correct_int_parameters(self):
        self.stack = self.create_stack(not_string_alarm_template)

        self.m.ReplayAll()
        self.stack.create()
        rsrc = self.stack['MEMAlarmHigh']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertIsNone(rsrc.validate())

        self.assertIsInstance(rsrc.properties['evaluation_periods'], int)
        self.assertIsInstance(rsrc.properties['period'], int)
        self.assertIsInstance(rsrc.properties['threshold'], int)

        self.m.VerifyAll()

    def test_mem_alarm_high_not_correct_string_parameters(self):
        snippet = template_format.parse(not_string_alarm_template)
        for p in ('period', 'evaluation_periods'):
            snippet['Resources']['MEMAlarmHigh']['Properties'][p] = '60a'
            stack = utils.parse_stack(snippet)

            rsrc = alarm.CeilometerAlarm(
                'MEMAlarmHigh', snippet['Resources']['MEMAlarmHigh'], stack)
            error = self.assertRaises(exception.StackValidationFailed,
                                      rsrc.validate)
            self.assertEqual(
                "Property error : MEMAlarmHigh: %s Value '60a' is not an "
                "integer" % p, str(error))

    def test_mem_alarm_high_not_integer_parameters(self):
        snippet = template_format.parse(not_string_alarm_template)
        for p in ('period', 'evaluation_periods'):
            snippet['Resources']['MEMAlarmHigh']['Properties'][p] = [60]
            stack = utils.parse_stack(snippet)

            rsrc = alarm.CeilometerAlarm(
                'MEMAlarmHigh', snippet['Resources']['MEMAlarmHigh'], stack)
            error = self.assertRaises(exception.StackValidationFailed,
                                      rsrc.validate)
            self.assertEqual(
                "Property error : MEMAlarmHigh: %s int() argument must be "
                "a string or a number, not 'list'" % p, str(error))

    def test_mem_alarm_high_check_not_required_parameters(self):
        snippet = template_format.parse(not_string_alarm_template)
        snippet['Resources']['MEMAlarmHigh']['Properties'].pop('meter_name')
        stack = utils.parse_stack(snippet)

        rsrc = alarm.CeilometerAlarm(
            'MEMAlarmHigh', snippet['Resources']['MEMAlarmHigh'], stack)
        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.validate)
        self.assertEqual(
            "Property error : MEMAlarmHigh: Property meter_name not assigned",
            str(error))

        for p in ('period', 'evaluation_periods', 'statistic',
                  'comparison_operator'):
            snippet = template_format.parse(not_string_alarm_template)
            snippet['Resources']['MEMAlarmHigh']['Properties'].pop(p)
            stack = utils.parse_stack(snippet)

            rsrc = alarm.CeilometerAlarm(
                'MEMAlarmHigh', snippet['Resources']['MEMAlarmHigh'], stack)
            self.assertIsNone(rsrc.validate())

    def test_delete_alarm_not_found(self):
        t = template_format.parse(alarm_template)

        self.stack = self.create_stack(template=json.dumps(t))
        self.m.StubOutWithMock(self.fa.alarms, 'delete')
        self.fa.alarms.delete('foo').AndRaise(
            alarm.ceilometerclient_exc.HTTPNotFound())

        self.m.ReplayAll()
        self.stack.create()
        rsrc = self.stack['MEMAlarmHigh']

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()


@testtools.skipIf(ceilometerclient is None, 'ceilometerclient unavailable')
class CombinationAlarmTest(HeatTestCase):

    def setUp(self):
        super(CombinationAlarmTest, self).setUp()
        self.fc = FakeCeilometerClient()
        self.m.StubOutWithMock(clients.OpenStackClients, 'ceilometer')
        utils.setup_dummy_db()

    def create_alarm(self):
        clients.OpenStackClients.ceilometer().MultipleTimes().AndReturn(
            self.fc)
        self.m.StubOutWithMock(self.fc.alarms, 'create')
        self.fc.alarms.create(
            alarm_actions=[],
            description=u'Do stuff in combination',
            name=mox.IgnoreArg(), type='combination',
            combination_rule={'alarm_ids': [u'alarm1', u'alarm2'],
                              'operator': u'and'}
        ).AndReturn(FakeCeilometerAlarm())
        snippet = template_format.parse(combination_alarm_template)
        stack = utils.parse_stack(snippet)
        return alarm.CombinationAlarm(
            'CombinAlarm', snippet['Resources']['CombinAlarm'], stack)

    def test_create(self):
        rsrc = self.create_alarm()

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('foo', rsrc.resource_id)
        self.m.VerifyAll()

    def test_invalid_alarm_list(self):
        snippet = template_format.parse(combination_alarm_template)
        snippet['Resources']['CombinAlarm']['Properties']['alarm_ids'] = []
        stack = utils.parse_stack(snippet)
        rsrc = alarm.CombinationAlarm(
            'CombinAlarm', snippet['Resources']['CombinAlarm'], stack)
        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.validate)
        self.assertEqual(
            "Property error : CombinAlarm: alarm_ids length (0) is out of "
            "range (min: 1, max: None)", str(error))

    def test_update(self):
        rsrc = self.create_alarm()
        self.m.StubOutWithMock(self.fc.alarms, 'update')
        self.fc.alarms.update(
            alarm_id='foo',
            combination_rule={'alarm_ids': [u'alarm1', u'alarm3']})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['alarm_ids'] = ['alarm1', 'alarm3']
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

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
            alarm.ceilometerclient_exc.HTTPNotFound())
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
