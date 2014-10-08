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
from oslo.config import cfg
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.resources import autoscaling as asc
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests import utils


as_template = inline_templates.as_template


class TestAutoScalingGroupValidation(common.HeatTestCase):
    def setUp(self):
        super(TestAutoScalingGroupValidation, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()

    def validate_scaling_group(self, t, stack, resource_name):
        # create the launch configuration resource
        conf = stack['LaunchConfig']
        self.assertIsNone(conf.validate())
        scheduler.TaskRunner(conf.create)()
        self.assertEqual((conf.CREATE, conf.COMPLETE), conf.state)

        # create the group resource
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        return rsrc

    def test_toomany_vpc_zone_identifier(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['VPCZoneIdentifier'] = ['xxxx', 'yyyy']

        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()
        self.assertRaises(exception.NotSupported,
                          self.validate_scaling_group, t,
                          stack, 'WebServerGroup')

        self.m.VerifyAll()

    def test_invalid_min_size(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '-1'
        properties['MaxSize'] = '2'

        stack = utils.parse_stack(t, params=inline_templates.as_params)

        self.stub_ImageConstraint_validate()

        self.m.ReplayAll()
        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "The size of AutoScalingGroup can not be less than zero"
        self.assertEqual(expected_msg, six.text_type(e))
        self.m.VerifyAll()

    def test_invalid_max_size(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '3'
        properties['MaxSize'] = '1'

        stack = utils.parse_stack(t, params=inline_templates.as_params)

        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "MinSize can not be greater than MaxSize"
        self.assertEqual(expected_msg, six.text_type(e))
        self.m.VerifyAll()

    def test_invalid_desiredcapacity(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        properties['DesiredCapacity'] = '4'

        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.stub_ImageConstraint_validate()

        self.m.ReplayAll()
        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "DesiredCapacity must be between MinSize and MaxSize"
        self.assertEqual(expected_msg, six.text_type(e))
        self.m.VerifyAll()

    def test_invalid_desiredcapacity_zero(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        properties['DesiredCapacity'] = '0'

        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.stub_ImageConstraint_validate()

        self.m.ReplayAll()
        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "DesiredCapacity must be between MinSize and MaxSize"
        self.assertEqual(expected_msg, six.text_type(e))
        self.m.VerifyAll()

    def test_child_template_uses_min_size(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        defn = rsrc_defn.ResourceDefinition(
            'asg', 'AWS::AutoScaling::AutoScalingGroup',
            {'MinSize': 2, 'MaxSize': 5, 'LaunchConfigurationName': 'foo'})
        rsrc = asc.AutoScalingGroup('asg', defn, stack)

        rsrc._create_template = mock.Mock(return_value='tpl')

        self.assertEqual('tpl', rsrc.child_template())
        rsrc._create_template.assert_called_once_with(2)

    def test_child_template_uses_desired_capacity(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        defn = rsrc_defn.ResourceDefinition(
            'asg', 'AWS::AutoScaling::AutoScalingGroup',
            {'MinSize': 2, 'MaxSize': 5, 'DesiredCapacity': 3,
             'LaunchConfigurationName': 'foo'})
        rsrc = asc.AutoScalingGroup('asg', defn, stack)

        rsrc._create_template = mock.Mock(return_value='tpl')

        self.assertEqual('tpl', rsrc.child_template())
        rsrc._create_template.assert_called_once_with(3)
