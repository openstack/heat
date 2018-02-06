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
from heat.engine.resources.aws.autoscaling import scaling_policy as aws_sp
from heat.engine import scheduler
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests import utils


as_template = inline_templates.as_template
as_params = inline_templates.as_params


class TestAutoScalingPolicy(common.HeatTestCase):
    def create_scaling_policy(self, t, stack, resource_name):
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_validate_scaling_policy_ok(self):
        t = template_format.parse(inline_templates.as_template)
        t['Resources']['WebServerScaleUpPolicy']['Properties'][
            'ScalingAdjustment'] = 33
        t['Resources']['WebServerScaleUpPolicy']['Properties'][
            'AdjustmentType'] = 'PercentChangeInCapacity'
        t['Resources']['WebServerScaleUpPolicy']['Properties'][
            'MinAdjustmentStep'] = 2
        stack = utils.parse_stack(t, params=as_params)
        self.policy = stack['WebServerScaleUpPolicy']
        self.assertIsNone(self.policy.validate())

    def test_validate_scaling_policy_error(self):
        t = template_format.parse(inline_templates.as_template)
        t['Resources']['WebServerScaleUpPolicy']['Properties'][
            'ScalingAdjustment'] = 1
        t['Resources']['WebServerScaleUpPolicy']['Properties'][
            'AdjustmentType'] = 'ChangeInCapacity'
        t['Resources']['WebServerScaleUpPolicy']['Properties'][
            'MinAdjustmentStep'] = 2
        stack = utils.parse_stack(t, params=as_params)
        self.policy = stack['WebServerScaleUpPolicy']
        ex = self.assertRaises(exception.ResourcePropertyValueDependency,
                               self.policy.validate)
        self.assertIn('MinAdjustmentStep property should only '
                      'be specified for AdjustmentType with '
                      'value PercentChangeInCapacity.', six.text_type(ex))

    def test_scaling_policy_bad_group(self):
        t = template_format.parse(inline_templates.as_template_bad_group)
        stack = utils.parse_stack(t, params=as_params)

        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')

        ex = self.assertRaises(exception.ResourceFailure, up_policy.signal)
        self.assertIn('Alarm WebServerScaleUpPolicy could '
                      'not find scaling group', six.text_type(ex))

    def test_scaling_policy_adjust_no_action(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        group = stack['WebServerGroup']
        self.patchobject(group, 'adjust',
                         side_effect=resource.NoActionRequired())
        self.assertRaises(resource.NoActionRequired, up_policy.handle_signal)

    def test_scaling_policy_adjust_size_changed(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        group = stack['WebServerGroup']
        self.patchobject(group, 'resize')
        self.patchobject(group, '_lb_reload')
        mock_fin_scaling = self.patchobject(group, '_finished_scaling')
        with mock.patch.object(group,
                               '_check_scaling_allowed') as mock_isa:
            self.assertIsNone(up_policy.handle_signal())
            mock_isa.assert_called_once_with(60)
            mock_fin_scaling.assert_called_once_with(60,
                                                     'ChangeInCapacity : 1',
                                                     size_changed=True)

    def test_scaling_policy_cooldown_toosoon(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'WebServerScaleUpPolicy')
        group = stack['WebServerGroup']
        test = {'current': 'alarm'}

        with mock.patch.object(
                group, '_check_scaling_allowed',
                side_effect=resource.NoActionRequired) as mock_isa:
            self.assertRaises(resource.NoActionRequired,
                              pol.handle_signal, details=test)
            mock_isa.assert_called_once_with(60)

    def test_scaling_policy_cooldown_ok(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        pol = self.create_scaling_policy(t, stack, 'WebServerScaleUpPolicy')
        group = stack['WebServerGroup']
        test = {'current': 'alarm'}
        self.patchobject(group, '_finished_scaling')
        self.patchobject(group, '_lb_reload')
        mock_resize = self.patchobject(group, 'resize')

        with mock.patch.object(group, '_check_scaling_allowed') as mock_isa:
            pol.handle_signal(details=test)
            mock_isa.assert_called_once_with(60)
        mock_resize.assert_called_once_with(1)

    @mock.patch.object(aws_sp.AWSScalingPolicy, '_get_ec2_signed_url')
    def test_scaling_policy_refid_signed_url(self, mock_get_ec2_url):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        rsrc = self.create_scaling_policy(t, stack, 'WebServerScaleUpPolicy')
        mock_get_ec2_url.return_value = 'http://signed_url'
        self.assertEqual('http://signed_url', rsrc.FnGetRefId())

    def test_scaling_policy_refid_rsrc_name(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=as_params)
        rsrc = self.create_scaling_policy(t, stack, 'WebServerScaleUpPolicy')
        rsrc.resource_id = None
        self.assertEqual('WebServerScaleUpPolicy', rsrc.FnGetRefId())

    def test_refid_convergence_cache_data(self):
        t = template_format.parse(as_template)
        cache_data = {'WebServerScaleUpPolicy': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'http://convg_signed_url'
        })}
        stack = utils.parse_stack(t, cache_data=cache_data)
        rsrc = stack.defn['WebServerScaleUpPolicy']
        self.assertEqual('http://convg_signed_url', rsrc.FnGetRefId())


class ScalingPolicyAttrTest(common.HeatTestCase):
    def setUp(self):
        super(ScalingPolicyAttrTest, self).setUp()
        t = template_format.parse(as_template)
        self.stack = utils.parse_stack(t, params=as_params)
        self.policy = self.stack['WebServerScaleUpPolicy']
        self.assertIsNone(self.policy.validate())
        scheduler.TaskRunner(self.policy.create)()
        self.assertEqual((self.policy.CREATE, self.policy.COMPLETE),
                         self.policy.state)

    def test_alarm_attribute(self):
        self.assertIn("WebServerScaleUpPolicy",
                      self.policy.FnGetAtt('AlarmUrl'))
