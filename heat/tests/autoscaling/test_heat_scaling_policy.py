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
from oslo_utils import timeutils
import six

from heat.common import exception
from heat.common import template_format
from heat.engine import scheduler
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests import utils


as_template = inline_templates.as_heat_template
as_params = inline_templates.as_params


class TestAutoScalingPolicy(common.HeatTestCase):

    def create_scaling_policy(self, t, stack, resource_name):
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_validate_scaling_policy_ok(self):
        t = template_format.parse(as_template)
        t['resources']['my-policy']['properties'][
            'scaling_adjustment'] = 33
        t['resources']['my-policy']['properties'][
            'adjustment_type'] = 'percent_change_in_capacity'
        t['resources']['my-policy']['properties'][
            'min_adjustment_step'] = 2
        stack = utils.parse_stack(t)
        self.assertIsNone(stack.validate())

    def test_validate_scaling_policy_error(self):
        t = template_format.parse(as_template)
        t['resources']['my-policy']['properties'][
            'scaling_adjustment'] = 1
        t['resources']['my-policy']['properties'][
            'adjustment_type'] = 'change_in_capacity'
        t['resources']['my-policy']['properties'][
            'min_adjustment_step'] = 2
        stack = utils.parse_stack(t)
        ex = self.assertRaises(exception.ResourcePropertyValueDependency,
                               stack.validate)
        self.assertIn('min_adjustment_step property should only '
                      'be specified for adjustment_type with '
                      'value percent_change_in_capacity.', six.text_type(ex))

    def test_scaling_policy_bad_group(self):
        t = template_format.parse(inline_templates.as_heat_template_bad_group)
        stack = utils.parse_stack(t)
        up_policy = self.create_scaling_policy(t, stack,
                                               'my-policy')

        ex = self.assertRaises(exception.ResourceFailure, up_policy.signal)
        self.assertIn('Alarm my-policy could '
                      'not find scaling group', six.text_type(ex))

    def test_scaling_policy_adjust_no_action(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        up_policy = self.create_scaling_policy(t, stack,
                                               'my-policy')
        group = stack['my-group']
        self.patchobject(group, 'adjust',
                         side_effect=exception.NoActionRequired())
        mock_fin_scaling = self.patchobject(up_policy, '_finished_scaling')
        with mock.patch.object(up_policy, '_is_scaling_allowed',
                               return_value=True) as mock_isa:
            self.assertRaises(exception.NoActionRequired,
                              up_policy.handle_signal)
            mock_isa.assert_called_once_with()
            mock_fin_scaling.assert_called_once_with('change_in_capacity : 1',
                                                     size_changed=False)

    def test_scaling_policy_adjust_size_changed(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        up_policy = self.create_scaling_policy(t, stack,
                                               'my-policy')
        group = stack['my-group']
        self.patchobject(group, 'adjust')
        mock_fin_scaling = self.patchobject(up_policy, '_finished_scaling')
        with mock.patch.object(up_policy, '_is_scaling_allowed',
                               return_value=True) as mock_isa:
            self.assertIsNone(up_policy.handle_signal())
            mock_isa.assert_called_once_with()
            mock_fin_scaling.assert_called_once_with('change_in_capacity : 1',
                                                     size_changed=True)

    def test_scaling_policy_not_alarm_state(self):
        """If the details don't have 'alarm' then don't progress."""
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        test = {'current': 'not_an_alarm'}
        with mock.patch.object(pol, '_is_scaling_allowed',
                               side_effect=AssertionError()) as dont_call:
            self.assertRaises(exception.NoActionRequired,
                              pol.handle_signal, details=test)
            self.assertEqual([], dont_call.call_args_list)

    def test_scaling_policy_cooldown_toosoon(self):
        """If _is_scaling_allowed() returns False don't progress."""
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')
        group = stack['my-group']
        test = {'current': 'alarm'}

        with mock.patch.object(group, 'adjust',
                               side_effect=AssertionError) as dont_call:
            with mock.patch.object(pol, '_is_scaling_allowed',
                                   return_value=False) as mock_cip:
                self.assertRaises(exception.NoActionRequired,
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
        with mock.patch.object(pol, '_is_scaling_allowed',
                               return_value=True) as mock_isa:
            pol.handle_signal(details=test)
            mock_isa.assert_called_once_with()
        group.adjust.assert_called_once_with(1, 'change_in_capacity', None)

    def test_scaling_policy_refid(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t)
        rsrc = stack['my-policy']
        rsrc.resource_id = 'xyz'
        self.assertEqual('xyz', rsrc.FnGetRefId())

    def test_scaling_policy_refid_convg_cache_data(self):
        t = template_format.parse(as_template)
        cache_data = {'my-policy': {
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'convg_xyz'
        }}
        stack = utils.parse_stack(t, cache_data=cache_data)
        rsrc = stack['my-policy']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())


class TestCooldownMixin(common.HeatTestCase):
    def setUp(self):
        super(TestCooldownMixin, self).setUp()

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
            now.isoformat(): 'change_in_capacity : 1'}}
        self.patchobject(pol, 'metadata_get', return_value=previous_meta)
        self.assertFalse(pol._is_scaling_allowed())

    def test_cooldown_is_in_progress_scaling_unfinished(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        previous_meta = {'scaling_in_progress': True}
        self.patchobject(pol, 'metadata_get', return_value=previous_meta)
        self.assertFalse(pol._is_scaling_allowed())

    def test_cooldown_not_in_progress(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        awhile_ago = timeutils.utcnow() - datetime.timedelta(seconds=100)
        previous_meta = {
            'cooldown': {
                awhile_ago.isoformat(): 'change_in_capacity : 1'
            },
            'scaling_in_progress': False
        }
        self.patchobject(pol, 'metadata_get', return_value=previous_meta)
        self.assertTrue(pol._is_scaling_allowed())

    def test_scaling_policy_cooldown_zero(self):
        t = template_format.parse(as_template)

        # Create the scaling policy (with cooldown=0) and scale up one
        properties = t['resources']['my-policy']['properties']
        properties['cooldown'] = '0'

        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        now = timeutils.utcnow()
        previous_meta = {'cooldown': {
            now.isoformat(): 'change_in_capacity : 1'}}
        self.patchobject(pol, 'metadata_get', return_value=previous_meta)
        self.assertTrue(pol._is_scaling_allowed())

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
            now.isoformat(): 'change_in_capacity : 1'}}
        self.patchobject(pol, 'metadata_get', return_value=previous_meta)
        self.assertTrue(pol._is_scaling_allowed())

    def test_no_cooldown_no_scaling_in_progress(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        # no cooldown entry in the metadata
        previous_meta = {'scaling_in_progress': False}
        self.patchobject(pol, 'metadata_get', return_value=previous_meta)
        self.assertTrue(pol._is_scaling_allowed())

    def test_metadata_is_written(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')

        nowish = timeutils.utcnow()
        reason = 'cool as'
        meta_set = self.patchobject(pol, 'metadata_set')
        self.patchobject(timeutils, 'utcnow', return_value=nowish)
        pol._finished_scaling(reason, size_changed=True)
        meta_set.assert_called_once_with(
            {'cooldown': {nowish.isoformat(): reason},
             'scaling_in_progress': False})


class ScalingPolicyAttrTest(common.HeatTestCase):
    def setUp(self):
        super(ScalingPolicyAttrTest, self).setUp()
        t = template_format.parse(as_template)
        self.stack = utils.parse_stack(t, params=as_params)
        self.stack_name = self.stack.name
        self.policy = self.stack['my-policy']
        self.assertIsNone(self.policy.validate())
        scheduler.TaskRunner(self.policy.create)()
        self.assertEqual((self.policy.CREATE, self.policy.COMPLETE),
                         self.policy.state)

    def test_alarm_attribute(self):
        self.m.StubOutWithMock(self.stack.clients.client_plugin('heat'),
                               'get_heat_cfn_url')
        self.stack.clients.client_plugin('heat').get_heat_cfn_url().AndReturn(
            'http://server.test:8000/v1')
        self.m.ReplayAll()
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

        args = sorted(alarm_url.split('?')[1].split('&'))
        self.assertEqual('AWSAccessKeyId', args[0].split('=')[0])
        self.assertEqual('Signature', args[1].split('=')[0])
        self.assertEqual('SignatureMethod', args[2].split('=')[0])
        self.assertEqual('SignatureVersion', args[3].split('=')[0])
        self.assertEqual('Timestamp', args[4].split('=')[0])
        self.m.VerifyAll()

    def test_signal_attribute(self):
        self.m.StubOutWithMock(self.stack.clients.client_plugin('heat'),
                               'get_heat_url')
        self.stack.clients.client_plugin('heat').get_heat_url().AndReturn(
            'http://server.test:8000/v1')
        self.m.ReplayAll()
        self.assertEqual(
            'http://server.test:8000/v1/test_tenant_id/stacks/'
            '%s/%s/resources/my-policy/signal' % (
                self.stack.name, self.stack.id),
            self.policy.FnGetAtt('signal_url'))
        self.m.VerifyAll()
