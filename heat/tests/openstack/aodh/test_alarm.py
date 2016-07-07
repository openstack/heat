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
import json

import mock
import mox
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import aodh
from heat.engine.clients.os import ceilometer
from heat.engine.resources.openstack.aodh import alarm
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template as tmpl
from heat.engine import watchrule
from heat.tests import common
from heat.tests import utils


alarm_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Alarm Test",
  "Parameters" : {},
  "Resources" : {
    "MEMAlarmHigh": {
     "Type": "OS::Aodh::Alarm",
     "Properties": {
        "description": "Scale-up if MEM > 50% for 1 minute",
        "meter_name": "MemoryUtilization",
        "statistic": "avg",
        "period": "60",
        "evaluation_periods": "1",
        "threshold": "50",
        "alarm_actions": [],
        "matching_metadata": {},
        "comparison_operator": "gt",
      }
    },
    "signal_handler" : {
      "Type" : "SignalResourceType"
    }
  }
}
'''

alarm_template_with_time_constraints = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Alarm Test",
  "Parameters" : {},
  "Resources" : {
    "MEMAlarmHigh": {
     "Type": "OS::Aodh::Alarm",
     "Properties": {
        "description": "Scale-up if MEM > 50% for 1 minute",
        "meter_name": "MemoryUtilization",
        "statistic": "avg",
        "period": "60",
        "evaluation_periods": "1",
        "threshold": "50",
        "alarm_actions": [],
        "matching_metadata": {},
        "comparison_operator": "gt",
        "time_constraints":
        [{"name": "tc1",
        "start": "0 23 * * *",
        "timezone": "Asia/Taipei",
        "duration": 10800,
        "description": "a description"
        }]
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
     "Type": "OS::Aodh::Alarm",
     "Properties": {
        "description": "Scale-up if MEM > 50% for 1 minute",
        "meter_name": "MemoryUtilization",
        "statistic": "avg",
        "period": 60,
        "evaluation_periods": 1,
        "threshold": 50,
        "alarm_actions": [],
        "matching_metadata": {},
        "comparison_operator": "gt",
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
     "Type": "OS::Aodh::CombinationAlarm",
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


class FakeCombinationAlarm(object):
    alarm_id = 'foo'

    def __init__(self):
        self.to_dict = lambda: {'attr': 'val'}


FakeAodhAlarm = {'other_attrs': 'val',
                 'alarm_id': 'foo'}


class AodhAlarmTest(common.HeatTestCase):
    def setUp(self):
        super(AodhAlarmTest, self).setUp()
        self.fa = mock.Mock()

    def create_stack(self, template=None, time_constraints=None):
        if template is None:
            template = alarm_template
        temp = template_format.parse(template)
        template = tmpl.Template(temp)
        ctx = utils.dummy_context()
        ctx.tenant = 'test_tenant'
        stack = parser.Stack(ctx, utils.random_name(), template,
                             disable_rollback=True)
        stack.store()

        self.patchobject(aodh.AodhClientPlugin,
                         '_create').return_value = self.fa

        al = copy.deepcopy(temp['Resources']['MEMAlarmHigh']['Properties'])
        al['time_constraints'] = time_constraints if time_constraints else []

        self.patchobject(self.fa.alarm, 'create').return_value = FakeAodhAlarm

        return stack

    def test_mem_alarm_high_update_no_replace(self):
        """Tests update updatable properties without replacing the Alarm."""

        # short circuit the alarm's references
        t = template_format.parse(alarm_template)
        properties = t['Resources']['MEMAlarmHigh']['Properties']
        properties['alarm_actions'] = ['signal_handler']
        properties['matching_metadata'] = {'a': 'v'}
        properties['query'] = [dict(field='b', op='eq', value='w')]

        test_stack = self.create_stack(template=json.dumps(t))

        update_mock = self.patchobject(self.fa.alarm, 'update')

        test_stack.create()
        rsrc = test_stack['MEMAlarmHigh']

        update_props = copy.deepcopy(rsrc.properties.data)
        update_props.update({
            'comparison_operator': 'lt',
            'description': 'fruity',
            'evaluation_periods': '2',
            'period': '90',
            'enabled': True,
            'repeat_actions': True,
            'statistic': 'max',
            'threshold': '39',
            'insufficient_data_actions': [],
            'alarm_actions': [],
            'ok_actions': ['signal_handler'],
            'matching_metadata': {'x': 'y'},
            'query': [dict(field='c', op='ne', value='z')]
        })

        snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                               rsrc.type(),
                                               update_props)

        scheduler.TaskRunner(rsrc.update, snippet)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(1, update_mock.call_count)

    def test_mem_alarm_high_update_replace(self):
        """Tests resource replacing when changing non-updatable properties."""

        t = template_format.parse(alarm_template)
        properties = t['Resources']['MEMAlarmHigh']['Properties']
        properties['alarm_actions'] = ['signal_handler']
        properties['matching_metadata'] = {'a': 'v'}

        test_stack = self.create_stack(template=json.dumps(t))

        test_stack.create()
        rsrc = test_stack['MEMAlarmHigh']

        properties = copy.copy(rsrc.properties.data)
        properties['meter_name'] = 'temp'
        snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                               rsrc.type(),
                                               properties)

        updater = scheduler.TaskRunner(rsrc.update, snippet)
        self.assertRaises(exception.UpdateReplace, updater)

    def test_mem_alarm_suspend_resume(self):
        """Tests suspending and resuming of the alarm.

        Make sure that the Alarm resource gets disabled on suspend
        and re-enabled on resume.
        """
        test_stack = self.create_stack()

        update_mock = self.patchobject(self.fa.alarm, 'update')
        al_suspend = {'enabled': False}
        al_resume = {'enabled': True}

        test_stack.create()
        rsrc = test_stack['MEMAlarmHigh']
        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)

        update_mock.assert_has_calls((
            mock.call('foo', al_suspend),
            mock.call('foo', al_resume)))

    def test_mem_alarm_high_correct_int_parameters(self):
        test_stack = self.create_stack(not_string_alarm_template)

        test_stack.create()
        rsrc = test_stack['MEMAlarmHigh']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertIsNone(rsrc.validate())

        self.assertIsInstance(rsrc.properties['evaluation_periods'], int)
        self.assertIsInstance(rsrc.properties['period'], int)
        self.assertIsInstance(rsrc.properties['threshold'], int)

    def test_alarm_metadata_prefix(self):
        t = template_format.parse(alarm_template)
        properties = t['Resources']['MEMAlarmHigh']['Properties']
        # Test for bug/1383521, where meter_name is in NOVA_METERS
        properties[alarm.AodhAlarm.METER_NAME] = 'memory.usage'
        properties['matching_metadata'] = {'metadata.user_metadata.groupname':
                                           'foo'}

        test_stack = self.create_stack(template=json.dumps(t))

        rsrc = test_stack['MEMAlarmHigh']
        rsrc.properties.data = rsrc.get_alarm_props(properties)
        self.assertIsNone(rsrc.properties.data.get('matching_metadata'))
        query = rsrc.properties.data['threshold_rule']['query']
        expected_query = [{'field': u'metadata.user_metadata.groupname',
                           'value': u'foo', 'op': 'eq'}]
        self.assertEqual(expected_query, query)

    def test_alarm_metadata_correct_query_key(self):
        t = template_format.parse(alarm_template)
        properties = t['Resources']['MEMAlarmHigh']['Properties']
        # Test that meter_name is not in NOVA_METERS
        properties[alarm.AodhAlarm.METER_NAME] = 'memory_util'
        properties['matching_metadata'] = {'metadata.user_metadata.groupname':
                                           'foo'}
        self.stack = self.create_stack(template=json.dumps(t))

        rsrc = self.stack['MEMAlarmHigh']
        rsrc.properties.data = rsrc.get_alarm_props(properties)
        self.assertIsNone(rsrc.properties.data.get('matching_metadata'))
        query = rsrc.properties.data['threshold_rule']['query']
        expected_query = [{'field': u'metadata.metering.groupname',
                           'value': u'foo', 'op': 'eq'}]
        self.assertEqual(expected_query, query)

    def test_mem_alarm_high_correct_matching_metadata(self):
        t = template_format.parse(alarm_template)
        properties = t['Resources']['MEMAlarmHigh']['Properties']
        properties['matching_metadata'] = {'fro': 'bar',
                                           'bro': True,
                                           'dro': 1234,
                                           'pro': '{"Mem": {"Ala": {"Hig"}}}',
                                           'tro': [1, 2, 3, 4]}

        test_stack = self.create_stack(template=json.dumps(t))

        test_stack.create()
        rsrc = test_stack['MEMAlarmHigh']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.properties.data = rsrc.get_alarm_props(properties)
        self.assertIsNone(rsrc.properties.data.get('matching_metadata'))
        for key in rsrc.properties.data['threshold_rule']['query']:
            self.assertIsInstance(key['value'], six.text_type)

    def test_no_matching_metadata(self):
        """Make sure that we can pass in an empty matching_metadata."""

        t = template_format.parse(alarm_template)
        properties = t['Resources']['MEMAlarmHigh']['Properties']
        properties['alarm_actions'] = ['signal_handler']
        del properties['matching_metadata']

        test_stack = self.create_stack(template=json.dumps(t))

        test_stack.create()
        rsrc = test_stack['MEMAlarmHigh']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertIsNone(rsrc.validate())

    def test_mem_alarm_high_not_correct_string_parameters(self):
        orig_snippet = template_format.parse(not_string_alarm_template)
        for p in ('period', 'evaluation_periods'):
            snippet = copy.deepcopy(orig_snippet)
            snippet['Resources']['MEMAlarmHigh']['Properties'][p] = '60a'
            stack = utils.parse_stack(snippet)

            resource_defns = stack.t.resource_definitions(stack)
            rsrc = alarm.AodhAlarm(
                'MEMAlarmHigh', resource_defns['MEMAlarmHigh'], stack)
            error = self.assertRaises(exception.StackValidationFailed,
                                      rsrc.validate)
            self.assertEqual(
                "Property error: Resources.MEMAlarmHigh.Properties.%s: "
                "Value '60a' is not an integer" % p, six.text_type(error))

    def test_mem_alarm_high_not_integer_parameters(self):
        orig_snippet = template_format.parse(not_string_alarm_template)
        for p in ('period', 'evaluation_periods'):
            snippet = copy.deepcopy(orig_snippet)
            snippet['Resources']['MEMAlarmHigh']['Properties'][p] = [60]
            stack = utils.parse_stack(snippet)

            resource_defns = stack.t.resource_definitions(stack)
            rsrc = alarm.AodhAlarm(
                'MEMAlarmHigh', resource_defns['MEMAlarmHigh'], stack)
            # python 3.4.3 returns another error message
            # so try to handle this by regexp
            msg = ("Property error: Resources.MEMAlarmHigh.Properties.%s: "
                   "int\(\) argument must be a string(, a bytes-like "
                   "object)? or a number, not 'list'" % p)
            self.assertRaisesRegexp(exception.StackValidationFailed,
                                    msg, rsrc.validate)

    def test_mem_alarm_high_check_not_required_parameters(self):
        snippet = template_format.parse(not_string_alarm_template)
        snippet['Resources']['MEMAlarmHigh']['Properties'].pop('meter_name')
        stack = utils.parse_stack(snippet)

        resource_defns = stack.t.resource_definitions(stack)
        rsrc = alarm.AodhAlarm(
            'MEMAlarmHigh', resource_defns['MEMAlarmHigh'], stack)
        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.validate)
        self.assertEqual(
            "Property error: Resources.MEMAlarmHigh.Properties: "
            "Property meter_name not assigned",
            six.text_type(error))

        for p in ('period', 'evaluation_periods', 'statistic',
                  'comparison_operator'):
            snippet = template_format.parse(not_string_alarm_template)
            snippet['Resources']['MEMAlarmHigh']['Properties'].pop(p)
            stack = utils.parse_stack(snippet)

            resource_defns = stack.t.resource_definitions(stack)
            rsrc = alarm.AodhAlarm(
                'MEMAlarmHigh', resource_defns['MEMAlarmHigh'], stack)
            self.assertIsNone(rsrc.validate())

    def test_delete_watchrule_destroy(self):
        t = template_format.parse(alarm_template)

        test_stack = self.create_stack(template=json.dumps(t))
        rsrc = test_stack['MEMAlarmHigh']

        wr = mock.MagicMock()
        self.patchobject(watchrule.WatchRule, 'load', return_value=wr)
        wr.destroy.return_value = None

        self.patchobject(aodh.AodhClientPlugin, 'client',
                         return_value=self.fa)
        self.patchobject(self.fa.alarm, 'delete')
        rsrc.resource_id = '12345'

        self.assertEqual('12345', rsrc.handle_delete())
        self.assertEqual(1, wr.destroy.call_count)
        # check that super method has been called and execute deleting
        self.assertEqual(1, self.fa.alarm.delete.call_count)

    def test_delete_no_watchrule(self):
        t = template_format.parse(alarm_template)

        test_stack = self.create_stack(template=json.dumps(t))
        rsrc = test_stack['MEMAlarmHigh']

        wr = mock.MagicMock()
        self.patchobject(watchrule.WatchRule, 'load',
                         side_effect=[exception.EntityNotFound(
                             entity='Watch Rule', name='test')])
        wr.destroy.return_value = None

        self.patchobject(aodh.AodhClientPlugin, 'client',
                         return_value=self.fa)
        self.patchobject(self.fa.alarm, 'delete')
        rsrc.resource_id = '12345'

        self.assertEqual('12345', rsrc.handle_delete())
        self.assertEqual(0, wr.destroy.call_count)
        # check that super method has been called and execute deleting
        self.assertEqual(1, self.fa.alarm.delete.call_count)

    def _prepare_check_resource(self):
        snippet = template_format.parse(not_string_alarm_template)
        self.stack = utils.parse_stack(snippet)
        res = self.stack['MEMAlarmHigh']
        res.client = mock.Mock()
        mock_alarm = mock.Mock(enabled=True, state='ok')
        res.client().alarm.get.return_value = mock_alarm
        return res

    @mock.patch.object(alarm.watchrule.WatchRule, 'load')
    def test_check(self, mock_load):
        res = self._prepare_check_resource()
        scheduler.TaskRunner(res.check)()
        self.assertEqual((res.CHECK, res.COMPLETE), res.state)

    @mock.patch.object(alarm.watchrule.WatchRule, 'load')
    def test_check_watchrule_failure(self, mock_load):
        res = self._prepare_check_resource()
        exc = alarm.exception.EntityNotFound(entity='Watch Rule', name='Boom')
        mock_load.side_effect = exc

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(res.check))
        self.assertEqual((res.CHECK, res.FAILED), res.state)
        self.assertIn('Boom', res.status_reason)

    @mock.patch.object(alarm.watchrule.WatchRule, 'load')
    def test_check_alarm_failure(self, mock_load):
        res = self._prepare_check_resource()
        res.client().alarm.get.side_effect = Exception('Boom')

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(res.check))
        self.assertEqual((res.CHECK, res.FAILED), res.state)
        self.assertIn('Boom', res.status_reason)

    def test_show_resource(self):
        res = self._prepare_check_resource()
        res.client().alarm.create.return_value = FakeAodhAlarm
        res.client().alarm.get.return_value = FakeAodhAlarm
        scheduler.TaskRunner(res.create)()
        self.assertEqual(FakeAodhAlarm, res.FnGetAtt('show'))

    def test_alarm_with_wrong_start_time(self):
        t = template_format.parse(alarm_template_with_time_constraints)
        time_constraints = [{"name": "tc1",
                             "start": "0 23 * * *",
                             "timezone": "Asia/Taipei",
                             "duration": 10800,
                             "description": "a description"
                             }]
        test_stack = self.create_stack(template=json.dumps(t),
                                       time_constraints=time_constraints)
        test_stack.create()
        self.assertEqual((test_stack.CREATE, test_stack.COMPLETE),
                         test_stack.state)

        rsrc = test_stack['MEMAlarmHigh']

        properties = copy.copy(rsrc.properties.data)
        start_time = '* * * * * 100'
        properties.update({
            'comparison_operator': 'lt',
            'description': 'fruity',
            'evaluation_periods': '2',
            'period': '90',
            'enabled': True,
            'repeat_actions': True,
            'statistic': 'max',
            'threshold': '39',
            'insufficient_data_actions': [],
            'alarm_actions': [],
            'ok_actions': ['signal_handler'],
            'matching_metadata': {'x': 'y'},
            'query': [dict(field='c', op='ne', value='z')],
            'time_constraints': [{"name": "tc1",
                                  "start": start_time,
                                  "timezone": "Asia/Taipei",
                                  "duration": 10800,
                                  "description": "a description"
                                  }]
        })
        snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                               rsrc.type(),
                                               properties)
        error = self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(rsrc.update, snippet)
        )
        self.assertEqual(
            "StackValidationFailed: resources.MEMAlarmHigh: Property error: "
            "MEMAlarmHigh.Properties.time_constraints[0].start: Error "
            "validating value '%s': Invalid CRON expression: "
            "[%s] is not acceptable, out of range" % (start_time, start_time),
            error.message)

    def test_alarm_with_wrong_timezone(self):
        t = template_format.parse(alarm_template_with_time_constraints)
        time_constraints = [{"name": "tc1",
                             "start": "0 23 * * *",
                             "timezone": "Asia/Taipei",
                             "duration": 10800,
                             "description": "a description"
                             }]
        test_stack = self.create_stack(template=json.dumps(t),
                                       time_constraints=time_constraints)
        test_stack.create()
        self.assertEqual((test_stack.CREATE, test_stack.COMPLETE),
                         test_stack.state)

        rsrc = test_stack['MEMAlarmHigh']

        properties = copy.copy(rsrc.properties.data)
        timezone = 'wrongtimezone'
        properties.update({
            'comparison_operator': 'lt',
            'description': 'fruity',
            'evaluation_periods': '2',
            'period': '90',
            'enabled': True,
            'repeat_actions': True,
            'statistic': 'max',
            'threshold': '39',
            'insufficient_data_actions': [],
            'alarm_actions': [],
            'ok_actions': ['signal_handler'],
            'matching_metadata': {'x': 'y'},
            'query': [dict(field='c', op='ne', value='z')],
            'time_constraints': [{"name": "tc1",
                                  "start": "0 23 * * *",
                                  "timezone": timezone,
                                  "duration": 10800,
                                  "description": "a description"
                                  }]
        })
        snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                               rsrc.type(),
                                               properties)
        error = self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(rsrc.update, snippet)
        )
        self.assertEqual(
            "StackValidationFailed: resources.MEMAlarmHigh: Property error: "
            "MEMAlarmHigh.Properties.time_constraints[0].timezone: Error "
            "validating value '%s': Invalid timezone: '%s'"
            % (timezone, timezone),
            error.message)

    def test_alarm_live_state(self):
        snippet = template_format.parse(alarm_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['MEMAlarmHigh']
        self.client = mock.Mock()
        self.patchobject(alarm.AodhAlarm, 'client',
                         return_value=self.client)

        alarm_res = alarm.AodhAlarm('alarm', self.rsrc_defn, self.stack)
        alarm_res.create()
        value = {
            'description': 'Scale-up if MEM > 50% for 1 minute',
            'alarm_actions': [],
            'time_constraints': [],
            'threshold_rule': {
                'meter_name': 'MemoryUtilization',
                'statistic': 'avg',
                'period': '60',
                'evaluation_periods': '1',
                'threshold': '50',
                'matching_metadata': {},
                'comparison_operator': 'gt',
                'query': [{'field': 'c', 'op': 'ne', 'value': 'z'}]
            }
        }
        self.client.alarm.get.return_value = value
        expected_data = {
            'description': 'Scale-up if MEM > 50% for 1 minute',
            'alarm_actions': [],
            'statistic': 'avg',
            'period': '60',
            'evaluation_periods': '1',
            'threshold': '50',
            'matching_metadata': {},
            'comparison_operator': 'gt',
            'query': [{'field': 'c', 'op': 'ne', 'value': 'z'}],
            'repeat_actions': None,
            'ok_actions': None,
            'insufficient_data_actions': None,
            'severity': None,
            'enabled': None
        }
        reality = alarm_res.get_live_state(alarm_res.properties)
        self.assertEqual(expected_data, reality)


class CombinationAlarmTest(common.HeatTestCase):

    def setUp(self):
        super(CombinationAlarmTest, self).setUp()
        self.fc = mock.Mock()
        self.m.StubOutWithMock(ceilometer.CeilometerClientPlugin, '_create')

    def create_alarm(self):
        ceilometer.CeilometerClientPlugin._create().AndReturn(
            self.fc)
        self.m.StubOutWithMock(self.fc.alarms, 'create')
        self.fc.alarms.create(
            alarm_actions=[],
            description=u'Do stuff in combination',
            enabled=True,
            insufficient_data_actions=None,
            ok_actions=None,
            name=mox.IgnoreArg(), type='combination',
            repeat_actions=True,
            combination_rule={'alarm_ids': [u'alarm1', u'alarm2'],
                              'operator': u'and'},
            time_constraints=[],
            severity='low'
        ).AndReturn(FakeCombinationAlarm())
        self.tmpl = template_format.parse(combination_alarm_template)
        self.stack = utils.parse_stack(self.tmpl)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return alarm.CombinationAlarm(
            'CombinAlarm', resource_defns['CombinAlarm'], self.stack)

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
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = alarm.CombinationAlarm(
            'CombinAlarm', resource_defns['CombinAlarm'], stack)
        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.validate)
        self.assertEqual(
            "Property error: Resources.CombinAlarm.Properties.alarm_ids: "
            "length (0) is out of range (min: 1, max: None)",
            six.text_type(error))

    def test_update(self):
        rsrc = self.create_alarm()
        self.m.StubOutWithMock(self.fc.alarms, 'update')
        self.fc.alarms.update(
            alarm_id='foo',
            combination_rule={'alarm_ids': [u'alarm1', u'alarm3']})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        props = self.tmpl['Resources']['CombinAlarm']['Properties'].copy()
        props['alarm_ids'] = ['alarm1', 'alarm3']
        update_template = rsrc.t.freeze(properties=props)
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

    def _prepare_check_resource(self):
        snippet = template_format.parse(combination_alarm_template)
        self.stack = utils.parse_stack(snippet)
        res = self.stack['CombinAlarm']
        res.client = mock.Mock()
        mock_alarm = mock.Mock(enabled=True, state='ok')
        res.client().alarms.get.return_value = mock_alarm
        return res

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
        res.client().alarms.get.return_value = FakeCombinationAlarm()
        scheduler.TaskRunner(res.create)()
        self.assertEqual({'attr': 'val'}, res.FnGetAtt('show'))
