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

import datetime

import mock
from oslo_config import cfg
from oslo_utils import timeutils
import six

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine import scheduler
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests import utils


as_template = inline_templates.as_heat_template
as_params = inline_templates.as_params


class TestAutoScalingPolicy(common.HeatTestCase):
    def setUp(self):
        super(TestAutoScalingPolicy, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')

    def create_scaling_policy(self, t, stack, resource_name):
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_scaling_policy_bad_group(self):
        t = template_format.parse(inline_templates.as_heat_template_bad_group)
        stack = utils.parse_stack(t)
        up_policy = self.create_scaling_policy(t, stack,
                                               'my-policy')

        ex = self.assertRaises(exception.ResourceFailure, up_policy.signal)
        self.assertIn('Alarm my-policy could '
                      'not find scaling group', six.text_type(ex))

    def test_scaling_policy_not_alarm_state(self):
        """If the details don't have 'alarm' then don't progress."""
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        test = {'current': 'not_an_alarm'}
        with mock.patch.object(pol, '_cooldown_inprogress',
                               side_effect=AssertionError()) as dont_call:
            self.assertRaises(resource.NoActionRequired,
                              pol.handle_signal, details=test)
            self.assertEqual([], dont_call.call_args_list)

    def test_scaling_policy_cooldown_toosoon(self):
        """If _cooldown_inprogress() returns True don't progress."""
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')
        test = {'current': 'alarm'}

        with mock.patch.object(pol.stack, 'resource_by_refid',
                               side_effect=AssertionError) as dont_call:
            with mock.patch.object(pol, '_cooldown_inprogress',
                                   return_value=True) as mock_cip:
                self.assertRaises(resource.NoActionRequired,
                                  pol.handle_signal, details=test)
                mock_cip.assert_called_once_with()
            self.assertEqual([], dont_call.call_args_list)

    def test_scaling_policy_cooldown_ok(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')
        test = {'current': 'alarm'}

        group = self.patchobject(pol.stack, 'resource_by_refid').return_value
        group.name = 'fluffy'
        with mock.patch.object(pol, '_cooldown_inprogress',
                               return_value=False) as mock_cip:
            pol.handle_signal(details=test)
            mock_cip.assert_called_once_with()
        group.adjust.assert_called_once_with(1, 'ChangeInCapacity')


class TestCooldownMixin(common.HeatTestCase):
    def setUp(self):
        super(TestCooldownMixin, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')

    def create_scaling_policy(self, t, stack, resource_name):
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_cooldown_is_in_progress_toosoon(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        now = timeutils.utcnow()
        previous_meta = {'cooldown': {
            now.isoformat(): 'ChangeInCapacity : 1'}}
        self.patchobject(pol, 'metadata_get', return_value=previous_meta)
        self.assertTrue(pol._cooldown_inprogress())

    def test_cooldown_is_in_progress_scaling_unfinished(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        previous_meta = {'scaling_in_progress': True}
        self.patchobject(pol, 'metadata_get', return_value=previous_meta)
        self.assertTrue(pol._cooldown_inprogress())

    def test_cooldown_not_in_progress(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        awhile_ago = timeutils.utcnow() - datetime.timedelta(seconds=100)
        previous_meta = {
            'cooldown': {
                awhile_ago.isoformat(): 'ChangeInCapacity : 1'
            },
            'scaling_in_progress': False
        }
        self.patchobject(pol, 'metadata_get', return_value=previous_meta)
        self.assertFalse(pol._cooldown_inprogress())

    def test_scaling_policy_cooldown_zero(self):
        t = template_format.parse(as_template)

        # Create the scaling policy (with cooldown=0) and scale up one
        properties = t['resources']['my-policy']['properties']
        properties['cooldown'] = '0'

        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        now = timeutils.utcnow()
        previous_meta = {'cooldown': {
            now.isoformat(): 'ChangeInCapacity : 1'}}
        self.patchobject(pol, 'metadata_get', return_value=previous_meta)
        self.assertFalse(pol._cooldown_inprogress())

    def test_scaling_policy_cooldown_none(self):
        t = template_format.parse(as_template)

        # Create the scaling policy no cooldown property, should behave the
        # same as when cooldown==0
        properties = t['resources']['my-policy']['properties']
        del properties['cooldown']

        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        now = timeutils.utcnow()
        previous_meta = {'cooldown': {
            now.isoformat(): 'ChangeInCapacity : 1'}}
        self.patchobject(pol, 'metadata_get', return_value=previous_meta)
        self.assertFalse(pol._cooldown_inprogress())

    def test_metadata_is_written(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        nowish = timeutils.utcnow()
        reason = 'cool as'
        meta_set = self.patchobject(pol, 'metadata_set')
        self.patchobject(timeutils, 'utcnow', return_value=nowish)
        pol._cooldown_timestamp(reason)
        meta_set.assert_called_once_with(
            {'cooldown': {nowish.isoformat(): reason},
             'scaling_in_progress': False})


class ScalingPolicyAttrTest(common.HeatTestCase):
    def setUp(self):
        super(ScalingPolicyAttrTest, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        t = template_format.parse(as_template)
        self.stack = utils.parse_stack(t, params=as_params)
        self.stack_name = self.stack.name
        self.policy = self.stack['my-policy']
        self.assertIsNone(self.policy.validate())
        scheduler.TaskRunner(self.policy.create)()
        self.assertEqual((self.policy.CREATE, self.policy.COMPLETE),
                         self.policy.state)

    def test_alarm_attribute(self):
        alarm_url = self.policy.FnGetAtt('alarm_url')

        base = alarm_url.split('?')[0].split('%3A')
        self.assertEqual('http://server.test:8000/v1/signal/arn', base[0])
        self.assertEqual('openstack', base[1])
        self.assertEqual('heat', base[2])
        self.assertEqual('test_tenant_id', base[4])

        res = base[5].split('%2F')
        self.assertEqual('stacks', res[0])
        self.assertEqual(self.stack_name, res[1])
        self.assertEqual('resources', res[3])
        self.assertEqual('my-policy', res[4])

        args = alarm_url.split('?')[1].split('&')
        self.assertEqual('Timestamp', args[0].split('=')[0])
        self.assertEqual('SignatureMethod', args[1].split('=')[0])
        self.assertEqual('AWSAccessKeyId', args[2].split('=')[0])
        self.assertEqual('SignatureVersion', args[3].split('=')[0])
        self.assertEqual('Signature', args[4].split('=')[0])
