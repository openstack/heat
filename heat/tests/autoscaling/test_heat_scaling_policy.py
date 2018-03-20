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
import six

from heat.common import exception
from heat.common import template_format
from heat.engine import node_data
from heat.engine import resource
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
        up_policy = self.create_scaling_policy(t, stack, 'my-policy')

        ex = self.assertRaises(exception.ResourceFailure, up_policy.signal)
        self.assertIn('Alarm my-policy could '
                      'not find scaling group', six.text_type(ex))

    def test_scaling_policy_adjust_no_action(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        up_policy = self.create_scaling_policy(t, stack, 'my-policy')
        group = stack['my-group']
        self.patchobject(group, 'adjust',
                         side_effect=resource.NoActionRequired())
        self.assertRaises(resource.NoActionRequired,
                          up_policy.handle_signal)

    def test_scaling_policy_adjust_size_changed(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        up_policy = self.create_scaling_policy(t, stack, 'my-policy')
        group = stack['my-group']
        self.patchobject(group, 'resize')
        self.patchobject(group, '_lb_reload')
        mock_fin_scaling = self.patchobject(group, '_finished_scaling')

        with mock.patch.object(group,
                               '_check_scaling_allowed') as mock_isa:
            self.assertIsNone(up_policy.handle_signal())
            mock_isa.assert_called_once_with(60)
            mock_fin_scaling.assert_called_once_with(60,
                                                     'change_in_capacity : 1',
                                                     size_changed=True)

    def test_scaling_policy_cooldown_toosoon(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')
        group = stack['my-group']
        test = {'current': 'alarm'}

        with mock.patch.object(
                group, '_check_scaling_allowed',
                side_effect=resource.NoActionRequired) as mock_cip:
            self.assertRaises(resource.NoActionRequired,
                              pol.handle_signal, details=test)
            mock_cip.assert_called_once_with(60)

    def test_scaling_policy_cooldown_ok(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'my-policy')
        group = stack['my-group']
        test = {'current': 'alarm'}
        self.patchobject(group, '_finished_scaling')
        self.patchobject(group, '_lb_reload')
        mock_resize = self.patchobject(group, 'resize')

        with mock.patch.object(group, '_check_scaling_allowed') as mock_isa:
            pol.handle_signal(details=test)
            mock_isa.assert_called_once_with(60)
        mock_resize.assert_called_once_with(1)

    def test_scaling_policy_refid(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t)
        rsrc = stack['my-policy']
        rsrc.resource_id = 'xyz'
        self.assertEqual('xyz', rsrc.FnGetRefId())

    def test_scaling_policy_refid_convg_cache_data(self):
        t = template_format.parse(as_template)
        cache_data = {'my-policy': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'convg_xyz'
        })}
        stack = utils.parse_stack(t, cache_data=cache_data)
        rsrc = stack.defn['my-policy']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())


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
        heat_plugin = self.stack.clients.client_plugin('heat')
        heat_plugin.get_heat_cfn_url = mock.Mock(
            return_value='http://server.test:8000/v1')
        alarm_url = self.policy.FnGetAtt('alarm_url')
        base = alarm_url.split('?')[0].split('%3A')
        self.assertEqual('http://server.test:8000/v1/signal/arn', base[0])
        self.assertEqual('openstack', base[1])
        self.assertEqual('heat', base[2])
        self.assertEqual('test_tenant_id', base[4])

        res = base[5].split('/')
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

    def test_signal_attribute(self):
        heat_plugin = self.stack.clients.client_plugin('heat')
        heat_plugin.get_heat_url = mock.Mock(
            return_value='http://server.test:8000/v1/')
        self.assertEqual(
            'http://server.test:8000/v1/test_tenant_id/stacks/'
            '%s/%s/resources/my-policy/signal' % (
                self.stack.name, self.stack.id),
            self.policy.FnGetAtt('signal_url'))

    def test_signal_attribute_with_prefix(self):
        heat_plugin = self.stack.clients.client_plugin('heat')
        heat_plugin.get_heat_url = mock.Mock(
            return_value='http://server.test/heat-api/v1/1234')
        self.assertEqual(
            'http://server.test/heat-api/v1/test_tenant_id/stacks/'
            '%s/%s/resources/my-policy/signal' % (
                self.stack.name, self.stack.id),
            self.policy.FnGetAtt('signal_url'))
