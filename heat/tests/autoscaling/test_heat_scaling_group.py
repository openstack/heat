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
from oslo_config import cfg
import six

from heat.common import exception
from heat.common import grouputils
from heat.common import template_format
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests import generic_resource
from heat.tests import utils


class TestAutoScalingGroupValidation(common.HeatTestCase):
    def setUp(self):
        super(TestAutoScalingGroupValidation, self).setUp()
        resource._register_class('ResourceWithPropsAndAttrs',
                                 generic_resource.ResourceWithPropsAndAttrs)
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()
        self.parsed = template_format.parse(inline_templates.as_heat_template)

    def test_invalid_min_size(self):
        self.parsed['resources']['my-group']['properties']['min_size'] = -1
        stack = utils.parse_stack(self.parsed)
        self.assertRaises(exception.StackValidationFailed,
                          stack['my-group'].validate)

    def test_invalid_max_size(self):
        self.parsed['resources']['my-group']['properties']['max_size'] = -1
        stack = utils.parse_stack(self.parsed)
        self.assertRaises(exception.StackValidationFailed,
                          stack['my-group'].validate)


class TestScalingGroupTags(common.HeatTestCase):
    def setUp(self):
        super(TestScalingGroupTags, self).setUp()
        t = template_format.parse(inline_templates.as_heat_template)
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = stack['my-group']

    def test_tags_default(self):
        expected = [{'Key': 'metering.groupname',
                     'Value': u'my-group'},
                    {'Key': 'metering.AutoScalingGroupName',
                     'Value': u'my-group'}]
        self.assertEqual(expected, self.group._tags())

    def test_tags_with_extra(self):
        self.group.properties.data['Tags'] = [
            {'Key': 'fee', 'Value': 'foo'}]
        expected = [{'Key': 'metering.groupname',
                     'Value': u'my-group'},
                    {'Key': 'metering.AutoScalingGroupName',
                     'Value': u'my-group'}]
        self.assertEqual(expected, self.group._tags())

    def test_tags_with_metering(self):
        self.group.properties.data['Tags'] = [
            {'Key': 'metering.fee', 'Value': 'foo'}]
        expected = [{'Key': 'metering.groupname', 'Value': 'my-group'},
                    {'Key': 'metering.AutoScalingGroupName',
                     'Value': u'my-group'}]

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
        t = template_format.parse(inline_templates.as_heat_template)
        properties = t['resources']['my-group']['properties']
        properties['min_size'] = self.mins
        properties['max_size'] = self.maxs
        properties['desired_capacity'] = self.desired
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        group = stack['my-group']
        with mock.patch.object(group, '_create_template') as mock_cre_temp:
            group.child_template()
            mock_cre_temp.assert_called_once_with(self.expected)


class TestGroupAdjust(common.HeatTestCase):
    def setUp(self):
        super(TestGroupAdjust, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        resource._register_class('ResourceWithPropsAndAttrs',
                                 generic_resource.ResourceWithPropsAndAttrs)
        self.stub_keystoneclient()

        t = template_format.parse(inline_templates.as_heat_template)
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = stack['my-group']
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
                groupname=u'my-group',
                message=u'Start resizing the group my-group',
                adjustment=1,
                stack=self.group.stack),
            mock.call(
                capacity=1, suffix='end',
                adjustment_type='ChangeInCapacity',
                groupname=u'my-group',
                message=u'End resizing the group my-group',
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
                groupname=u'my-group',
                message=u'Start resizing the group my-group',
                adjustment=1,
                stack=self.group.stack),
            mock.call(
                capacity=0, suffix='error',
                adjustment_type='ChangeInCapacity',
                groupname=u'my-group',
                message=u'test error',
                adjustment=1,
                stack=self.group.stack)]

        self.assertEqual(expected_notifies, notify.call_args_list)


class TestGroupCrud(common.HeatTestCase):
    def setUp(self):
        super(TestGroupCrud, self).setUp()
        resource._register_class('ResourceWithPropsAndAttrs',
                                 generic_resource.ResourceWithPropsAndAttrs)
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_SnapshotConstraint_validate()

        t = template_format.parse(inline_templates.as_heat_template)
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = stack['my-group']
        self.assertIsNone(self.group.validate())

    def test_handle_create(self):
        self.group.create_with_template = mock.Mock(return_value=None)
        self.group.child_template = mock.Mock(return_value='{}')

        self.group.handle_create()

        self.group.child_template.assert_called_once_with()
        self.group.create_with_template.assert_called_once_with('{}')

    def test_handle_update_desired_cap(self):
        self.group._try_rolling_update = mock.Mock(return_value=None)
        self.group.adjust = mock.Mock(return_value=None)

        props = {'desired_capacity': 4}
        defn = rsrc_defn.ResourceDefinition(
            'nopayload',
            'OS::Heat::AutoScalingGroup',
            props)

        self.group.handle_update(defn, None, props)

        self.group.adjust.assert_called_once_with(
            4, adjustment_type='ExactCapacity')
        self.group._try_rolling_update.assert_called_once_with(props)

    def test_handle_update_desired_nocap(self):
        self.group._try_rolling_update = mock.Mock(return_value=None)
        self.group.adjust = mock.Mock(return_value=None)
        get_size = self.patchobject(grouputils, 'get_size')
        get_size.return_value = 6

        props = {'Tags': []}
        defn = rsrc_defn.ResourceDefinition(
            'nopayload',
            'OS::Heat::AutoScalingGroup',
            props)

        self.group.handle_update(defn, None, props)

        self.group.adjust.assert_called_once_with(
            6, adjustment_type='ExactCapacity')
        self.group._try_rolling_update.assert_called_once_with(props)

    def test_update_in_failed(self):
        self.group.state_set('CREATE', 'FAILED')
        # to update the failed asg
        self.group.adjust = mock.Mock(return_value=None)

        new_defn = rsrc_defn.ResourceDefinition(
            'asg', 'OS::Heat::AutoScalingGroup',
            {'AvailabilityZones': ['nova'],
             'LaunchConfigurationName': 'config',
             'max_size': 5,
             'min_size': 1,
             'desired_capacity': 2,
             'resource':
             {'type': 'ResourceWithPropsAndAttrs',
              'properties': {
                  'Foo': 'hello'}}})

        self.group.handle_update(new_defn, None, None)
        self.group.adjust.assert_called_once_with(
            2, adjustment_type='ExactCapacity')


class HeatScalingGroupAttrTest(common.HeatTestCase):
    def setUp(self):
        super(HeatScalingGroupAttrTest, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        resource._register_class('ResourceWithPropsAndAttrs',
                                 generic_resource.ResourceWithPropsAndAttrs)
        self.stub_keystoneclient()

        t = template_format.parse(inline_templates.as_heat_template)
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = stack['my-group']
        self.assertIsNone(self.group.validate())

    def test_no_instance_list(self):
        """The InstanceList attribute is not inherited from
        AutoScalingResourceGroup's superclasses.
        """
        self.assertRaises(exception.InvalidTemplateAttribute,
                          self.group.FnGetAtt, 'InstanceList')

    def test_output_attribute_list(self):
        mock_members = self.patchobject(grouputils, 'get_members')
        members = []
        output = []
        for ip_ex in six.moves.range(1, 4):
            inst = mock.Mock()
            inst.FnGetAtt.return_value = '2.1.3.%d' % ip_ex
            output.append('2.1.3.%d' % ip_ex)
            members.append(inst)
        mock_members.return_value = members

        self.assertEqual(output, self.group.FnGetAtt('outputs_list', 'Bar'))

    def test_output_attribute_dict(self):
        mock_members = self.patchobject(grouputils, 'get_members')
        members = []
        output = {}
        for ip_ex in six.moves.range(1, 4):
            inst = mock.Mock()
            inst.name = str(ip_ex)
            inst.FnGetAtt.return_value = '2.1.3.%d' % ip_ex
            output[str(ip_ex)] = '2.1.3.%d' % ip_ex
            members.append(inst)
        mock_members.return_value = members

        self.assertEqual(output,
                         self.group.FnGetAtt('outputs', 'Bar'))

    def test_attribute_current_size(self):
        mock_instances = self.patchobject(grouputils, 'get_size')
        mock_instances.return_value = 3
        self.assertEqual(3, self.group.FnGetAtt('current_size'))

    def test_attribute_current_size_with_path(self):
        mock_instances = self.patchobject(grouputils, 'get_size')
        mock_instances.return_value = 4
        self.assertEqual(4, self.group.FnGetAtt('current_size', 'name'))

    def test_index_dotted_attribute(self):
        mock_members = self.patchobject(grouputils, 'get_members')
        members = []
        output = []
        for ip_ex in six.moves.range(0, 2):
            inst = mock.Mock()
            inst.name = str(ip_ex)
            inst.FnGetAtt.return_value = '2.1.3.%d' % ip_ex
            output.append('2.1.3.%d' % ip_ex)
            members.append(inst)
        mock_members.return_value = members
        self.assertEqual(output[0], self.group.FnGetAtt('resource.0', 'Bar'))
        self.assertEqual(output[1], self.group.FnGetAtt('resource.1.Bar'))
        self.assertRaises(exception.InvalidTemplateAttribute,
                          self.group.FnGetAtt, 'resource.2')
