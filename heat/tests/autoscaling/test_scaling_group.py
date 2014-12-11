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
from heat.common import grouputils
from heat.common import template_format
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
        self.stub_SnapshotConstraint_validate()

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
        self.stub_FlavorConstraint_validate()
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
        self.stub_FlavorConstraint_validate()

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
        self.stub_FlavorConstraint_validate()
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
        self.stub_FlavorConstraint_validate()
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
        self.stub_FlavorConstraint_validate()

        self.m.ReplayAll()
        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "DesiredCapacity must be between MinSize and MaxSize"
        self.assertEqual(expected_msg, six.text_type(e))
        self.m.VerifyAll()


class TestScalingGroupTags(common.HeatTestCase):
    def setUp(self):
        super(TestScalingGroupTags, self).setUp()
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = stack['WebServerGroup']

    def test_tags_default(self):
        expected = [{'Key': 'metering.groupname',
                     'Value': u'WebServerGroup'},
                    {'Key': 'metering.AutoScalingGroupName',
                     'Value': u'WebServerGroup'}]
        self.assertEqual(expected, self.group._tags())

    def test_tags_with_extra(self):
        self.group.properties.data['Tags'] = [
            {'Key': 'fee', 'Value': 'foo'}]
        expected = [{'Key': 'fee',
                     'Value': 'foo'},
                    {'Key': 'metering.groupname',
                     'Value': u'WebServerGroup'},
                    {'Key': 'metering.AutoScalingGroupName',
                     'Value': u'WebServerGroup'}]
        self.assertEqual(expected, self.group._tags())

    def test_tags_with_metering(self):
        self.group.properties.data['Tags'] = [
            {'Key': 'metering.fee', 'Value': 'foo'}]
        expected = [{'Key': 'metering.fee', 'Value': 'foo'},
                    {'Key': 'metering.AutoScalingGroupName',
                     'Value': u'WebServerGroup'}]

        self.assertEqual(expected, self.group._tags())


class TestInitialGroupSize(common.HeatTestCase):
    scenarios = [
        ('000', dict(mins=0, maxs=0, desired=0, expected=0)),
        ('040', dict(mins=0, maxs=4, desired=0, expected=0)),
        ('253', dict(mins=2, maxs=5, desired=3, expected=3)),
        ('14n', dict(mins=1, maxs=4, desired=None, expected=1)),
    ]

    def setUp(self):
        super(TestInitialGroupSize, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()

    def test_initial_size(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = self.mins
        properties['MaxSize'] = self.maxs
        properties['DesiredCapacity'] = self.desired
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        group = stack['WebServerGroup']
        with mock.patch.object(group, '_create_template') as mock_cre_temp:
            group.child_template()
            mock_cre_temp.assert_called_once_with(self.expected)


class TestGroupAdjust(common.HeatTestCase):
    def setUp(self):
        super(TestGroupAdjust, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()

        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = stack['WebServerGroup']
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.assertIsNone(self.group.validate())

    def test_scaling_policy_cooldown_toosoon(self):
        """If _cooldown_inprogress() returns True don't progress."""

        dont_call = self.patchobject(grouputils, 'get_members')
        with mock.patch.object(self.group, '_cooldown_inprogress',
                               return_value=True):
            self.group.adjust(1)
        self.assertEqual([], dont_call.call_args_list)

    def test_scaling_policy_cooldown_ok(self):
        self.patchobject(grouputils, 'get_members', return_value=[])
        resize = self.patchobject(self.group, 'resize')
        cd_stamp = self.patchobject(self.group, '_cooldown_timestamp')
        notify = self.patch('heat.engine.notification.autoscaling.send')
        self.patchobject(self.group, '_cooldown_inprogress',
                         return_value=False)
        self.group.adjust(1)

        expected_notifies = [
            mock.call(
                capacity=0, suffix='start', adjustment_type='ChangeInCapacity',
                groupname=u'WebServerGroup',
                message=u'Start resizing the group WebServerGroup',
                adjustment=1,
                stack=self.group.stack),
            mock.call(
                capacity=1, suffix='end',
                adjustment_type='ChangeInCapacity',
                groupname=u'WebServerGroup',
                message=u'End resizing the group WebServerGroup',
                adjustment=1,
                stack=self.group.stack)]

        self.assertEqual(expected_notifies, notify.call_args_list)
        resize.assert_called_once_with(1)
        cd_stamp.assert_called_once_with('ChangeInCapacity : 1')

    def test_scaling_policy_resize_fail(self):
        self.patchobject(grouputils, 'get_members', return_value=[])
        self.patchobject(self.group, 'resize',
                         side_effect=ValueError('test error'))
        notify = self.patch('heat.engine.notification.autoscaling.send')
        self.patchobject(self.group, '_cooldown_inprogress',
                         return_value=False)
        self.assertRaises(ValueError, self.group.adjust, 1)

        expected_notifies = [
            mock.call(
                capacity=0, suffix='start',
                adjustment_type='ChangeInCapacity',
                groupname=u'WebServerGroup',
                message=u'Start resizing the group WebServerGroup',
                adjustment=1,
                stack=self.group.stack),
            mock.call(
                capacity=0, suffix='error',
                adjustment_type='ChangeInCapacity',
                groupname=u'WebServerGroup',
                message=u'test error',
                adjustment=1,
                stack=self.group.stack)]

        self.assertEqual(expected_notifies, notify.call_args_list)
