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
import json

import mock
from oslo_utils import timeutils
import six

from heat.common import exception
from heat.common import grouputils
from heat.common import template_format
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests import utils


class TestAutoScalingGroupValidation(common.HeatTestCase):
    def setUp(self):
        super(TestAutoScalingGroupValidation, self).setUp()
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

    def test_validate_reference_attr_with_none_ref(self):
        stack = utils.parse_stack(self.parsed)
        group = stack['my-group']
        self.patchobject(group, 'referenced_attrs',
                         return_value=set([('something', None)]))
        self.assertIsNone(group.validate())


class TestScalingGroupTags(common.HeatTestCase):
    def setUp(self):
        super(TestScalingGroupTags, self).setUp()
        t = template_format.parse(inline_templates.as_heat_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = self.stack['my-group']

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

        t = template_format.parse(inline_templates.as_heat_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = self.stack['my-group']
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.assertIsNone(self.group.validate())

    def test_group_metadata_reset(self):
        self.group.state_set('CREATE', 'COMPLETE')
        metadata = {'scaling_in_progress': True}
        self.group.metadata_set(metadata)
        self.group.handle_metadata_reset()

        new_metadata = self.group.metadata_get()
        self.assertEqual({'scaling_in_progress': False}, new_metadata)

    def test_scaling_policy_cooldown_toosoon(self):
        dont_call = self.patchobject(self.group, 'resize')
        self.patchobject(self.group, '_check_scaling_allowed',
                         side_effect=resource.NoActionRequired)
        self.assertRaises(resource.NoActionRequired,
                          self.group.adjust, 1)
        self.assertEqual([], dont_call.call_args_list)

    def test_scaling_same_capacity(self):
        """Don't resize when capacity is the same."""
        self.patchobject(grouputils, 'get_size', return_value=3)
        resize = self.patchobject(self.group, 'resize')
        finished_scaling = self.patchobject(self.group, '_finished_scaling')
        notify = self.patch('heat.engine.notification.autoscaling.send')
        self.assertRaises(resource.NoActionRequired,
                          self.group.adjust, 3,
                          adjustment_type='ExactCapacity')
        expected_notifies = []
        self.assertEqual(expected_notifies, notify.call_args_list)
        self.assertEqual(0, resize.call_count)
        self.assertEqual(0, finished_scaling.call_count)

    def test_scale_up_min_adjustment(self):
        self.patchobject(grouputils, 'get_size', return_value=1)
        resize = self.patchobject(self.group, 'resize')
        finished_scaling = self.patchobject(self.group, '_finished_scaling')
        notify = self.patch('heat.engine.notification.autoscaling.send')
        self.patchobject(self.group, '_check_scaling_allowed')
        self.group.adjust(33, adjustment_type='PercentChangeInCapacity',
                          min_adjustment_step=2)

        expected_notifies = [
            mock.call(
                capacity=1, suffix='start',
                adjustment_type='PercentChangeInCapacity',
                groupname=u'my-group',
                message=u'Start resizing the group my-group',
                adjustment=33,
                stack=self.group.stack),
            mock.call(
                capacity=3, suffix='end',
                adjustment_type='PercentChangeInCapacity',
                groupname=u'my-group',
                message=u'End resizing the group my-group',
                adjustment=33,
                stack=self.group.stack)]

        self.assertEqual(expected_notifies, notify.call_args_list)
        resize.assert_called_once_with(3)
        finished_scaling.assert_called_once_with(
            None,
            'PercentChangeInCapacity : 33',
            size_changed=True)

    def test_scale_down_min_adjustment(self):
        self.patchobject(grouputils, 'get_size', return_value=3)
        resize = self.patchobject(self.group, 'resize')
        finished_scaling = self.patchobject(self.group, '_finished_scaling')
        notify = self.patch('heat.engine.notification.autoscaling.send')
        self.patchobject(self.group, '_check_scaling_allowed')
        self.group.adjust(-33, adjustment_type='PercentChangeInCapacity',
                          min_adjustment_step=2)

        expected_notifies = [
            mock.call(
                capacity=3, suffix='start',
                adjustment_type='PercentChangeInCapacity',
                groupname=u'my-group',
                message=u'Start resizing the group my-group',
                adjustment=-33,
                stack=self.group.stack),
            mock.call(
                capacity=1, suffix='end',
                adjustment_type='PercentChangeInCapacity',
                groupname=u'my-group',
                message=u'End resizing the group my-group',
                adjustment=-33,
                stack=self.group.stack)]

        self.assertEqual(expected_notifies, notify.call_args_list)
        resize.assert_called_once_with(1)
        finished_scaling.assert_called_once_with(
            None,
            'PercentChangeInCapacity : -33',
            size_changed=True)

    def test_scaling_policy_cooldown_ok(self):
        self.patchobject(grouputils, 'get_size', return_value=0)
        resize = self.patchobject(self.group, 'resize')
        finished_scaling = self.patchobject(self.group, '_finished_scaling')
        notify = self.patch('heat.engine.notification.autoscaling.send')
        self.patchobject(self.group, '_check_scaling_allowed')
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
        finished_scaling.assert_called_once_with(None,
                                                 'ChangeInCapacity : 1',
                                                 size_changed=True)
        grouputils.get_size.assert_called_once_with(self.group)

    def test_scaling_policy_resize_fail(self):
        self.patchobject(grouputils, 'get_size', return_value=0)
        self.patchobject(self.group, 'resize',
                         side_effect=ValueError('test error'))
        notify = self.patch('heat.engine.notification.autoscaling.send')
        self.patchobject(self.group, '_check_scaling_allowed')
        self.patchobject(self.group, '_finished_scaling')
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
        grouputils.get_size.assert_called_with(self.group)

    def test_notification_send_if_resize_failed(self):
        """If resize failed, the capacity of group might have been changed"""
        self.patchobject(grouputils, 'get_size', side_effect=[3, 4])
        self.patchobject(self.group, 'resize',
                         side_effect=ValueError('test error'))
        notify = self.patch('heat.engine.notification.autoscaling.send')
        self.patchobject(self.group, '_check_scaling_allowed')
        self.patchobject(self.group, '_finished_scaling')

        self.assertRaises(ValueError, self.group.adjust,
                          5, adjustment_type='ExactCapacity')

        expected_notifies = [
            mock.call(
                capacity=3, suffix='start',
                adjustment_type='ExactCapacity',
                groupname='my-group',
                message='Start resizing the group my-group',
                adjustment=5,
                stack=self.group.stack),
            mock.call(
                capacity=4, suffix='error',
                adjustment_type='ExactCapacity',
                groupname='my-group',
                message=u'test error',
                adjustment=5,
                stack=self.group.stack)]

        self.assertEqual(expected_notifies, notify.call_args_list)
        self.group.resize.assert_called_once_with(5)
        grouputils.get_size.assert_has_calls([mock.call(self.group),
                                              mock.call(self.group)])


class TestGroupCrud(common.HeatTestCase):
    def setUp(self):
        super(TestGroupCrud, self).setUp()
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_SnapshotConstraint_validate()

        t = template_format.parse(inline_templates.as_heat_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = self.stack['my-group']
        self.assertIsNone(self.group.validate())

    def test_handle_create(self):
        self.group.create_with_template = mock.Mock(return_value=None)
        self.group.child_template = mock.Mock(return_value='{}')

        self.group.handle_create()

        self.group.child_template.assert_called_once_with()
        self.group.create_with_template.assert_called_once_with('{}')

    def test_handle_update_desired_cap(self):
        self.group._try_rolling_update = mock.Mock(return_value=None)
        self.group.resize = mock.Mock(return_value=None)

        props = {'desired_capacity': 4,
                 'min_size': 0,
                 'max_size': 6}
        defn = rsrc_defn.ResourceDefinition(
            'nopayload',
            'OS::Heat::AutoScalingGroup',
            props)

        self.group.handle_update(defn, None, props)

        self.group.resize.assert_called_once_with(4)
        self.group._try_rolling_update.assert_called_once_with(props)

    def test_handle_update_desired_nocap(self):
        self.group._try_rolling_update = mock.Mock(return_value=None)
        self.group.resize = mock.Mock(return_value=None)
        get_size = self.patchobject(grouputils, 'get_size')
        get_size.return_value = 6

        props = {'min_size': 0,
                 'max_size': 6}
        defn = rsrc_defn.ResourceDefinition(
            'nopayload',
            'OS::Heat::AutoScalingGroup',
            props)

        self.group.handle_update(defn, None, props)

        self.group.resize.assert_called_once_with(6)
        self.group._try_rolling_update.assert_called_once_with(props)

    def test_update_in_failed(self):
        self.group.state_set('CREATE', 'FAILED')
        # to update the failed asg
        self.group.resize = mock.Mock(return_value=None)

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
        self.group.resize.assert_called_once_with(2)


class HeatScalingGroupAttrTest(common.HeatTestCase):
    def setUp(self):
        super(HeatScalingGroupAttrTest, self).setUp()

        t = template_format.parse(inline_templates.as_heat_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = self.stack['my-group']
        self.assertIsNone(self.group.validate())

    def test_no_instance_list(self):
        """Tests inheritance of InstanceList attribute.

        The InstanceList attribute is not inherited from
        AutoScalingResourceGroup's superclasses.
        """
        self.assertRaises(exception.InvalidTemplateAttribute,
                          self.group.FnGetAtt, 'InstanceList')

    def _stub_get_attr(self, refids, attrs):
        def ref_id_fn(res_name):
            return refids[res_name]

        def attr_fn(args):
            res_name = args[0]
            return attrs[res_name]

        inspector = self.group._group_data()
        member_names = sorted(refids if refids else attrs)
        self.patchobject(inspector, 'member_names', return_value=member_names)

        def get_output(output_name):
            outputs = self.group._nested_output_defns(member_names,
                                                      attr_fn, ref_id_fn)
            op_defns = {od.name: od for od in outputs}
            self.assertIn(output_name, op_defns)
            return op_defns[output_name].get_value()

        orig_get_attr = self.group.FnGetAtt

        def get_attr(attr_name, *path):
            if not path:
                attr = attr_name
            else:
                attr = (attr_name,) + path
            # Mock referenced_attrs() so that _nested_output_definitions()
            # will include the output required for this attribute
            self.group.referenced_attrs = mock.Mock(return_value=[attr])

            # Pass through to actual function under test
            return orig_get_attr(attr_name, *path)

        self.group.FnGetAtt = mock.Mock(side_effect=get_attr)
        self.group.get_output = mock.Mock(side_effect=get_output)

    def test_output_attribute_list(self):
        values = {str(i): '2.1.3.%d' % i for i in range(1, 4)}
        self._stub_get_attr({n: 'foo' for n in values}, values)

        expected = [v for k, v in sorted(values.items())]
        self.assertEqual(expected, self.group.FnGetAtt('outputs_list', 'Bar'))

    def test_output_attribute_dict(self):
        values = {str(i): '2.1.3.%d' % i for i in range(1, 4)}
        self._stub_get_attr({n: 'foo' for n in values}, values)

        self.assertEqual(values, self.group.FnGetAtt('outputs', 'Bar'))

    def test_index_dotted_attribute(self):
        values = {'ab'[i - 1]: '2.1.3.%d' % i for i in range(1, 3)}
        self._stub_get_attr({'a': 'foo', 'b': 'bar'}, values)

        self.assertEqual(values['a'], self.group.FnGetAtt('resource.0', 'Bar'))
        self.assertEqual(values['b'], self.group.FnGetAtt('resource.1.Bar'))
        self.assertRaises(exception.NotFound,
                          self.group.FnGetAtt, 'resource.2')

    def test_output_refs(self):
        values = {'abc': 'resource-1', 'def': 'resource-2'}
        self._stub_get_attr(values, {})

        expected = [v for k, v in sorted(values.items())]
        self.assertEqual(expected, self.group.FnGetAtt('refs'))

    def test_output_refs_map(self):
        values = {'abc': 'resource-1', 'def': 'resource-2'}
        self._stub_get_attr(values, {})

        self.assertEqual(values, self.group.FnGetAtt('refs_map'))

    def test_attribute_current_size(self):
        mock_instances = self.patchobject(grouputils, 'get_size')
        mock_instances.return_value = 3
        self.assertEqual(3, self.group.FnGetAtt('current_size'))

    def test_attribute_current_size_with_path(self):
        mock_instances = self.patchobject(grouputils, 'get_size')
        mock_instances.return_value = 4
        self.assertEqual(4, self.group.FnGetAtt('current_size', 'name'))


class HeatScalingGroupAttrFallbackTest(common.HeatTestCase):
    def setUp(self):
        super(HeatScalingGroupAttrFallbackTest, self).setUp()

        t = template_format.parse(inline_templates.as_heat_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = self.stack['my-group']
        self.assertIsNone(self.group.validate())

        # Raise NotFound when getting output, to force fallback to old-school
        # grouputils functions
        self.group.get_output = mock.Mock(side_effect=exception.NotFound)

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

    def test_output_refs(self):
        # Setup
        mock_get = self.patchobject(grouputils, 'get_member_refids')
        mock_get.return_value = ['resource-1', 'resource-2']

        # Test
        found = self.group.FnGetAtt('refs')

        # Verify
        expected = ['resource-1', 'resource-2']
        self.assertEqual(expected, found)
        mock_get.assert_called_once_with(self.group)

    def test_output_refs_map(self):
        # Setup
        mock_members = self.patchobject(grouputils, 'get_members')
        members = [mock.MagicMock(), mock.MagicMock()]
        members[0].name = 'resource-1-name'
        members[0].resource_id = 'resource-1-id'
        members[1].name = 'resource-2-name'
        members[1].resource_id = 'resource-2-id'
        mock_members.return_value = members

        # Test
        found = self.group.FnGetAtt('refs_map')

        # Verify
        expected = {'resource-1-name': 'resource-1-id',
                    'resource-2-name': 'resource-2-id'}
        self.assertEqual(expected, found)

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

    def test_index_dotted_attribute(self):
        mock_members = self.patchobject(grouputils, 'get_members')
        self.group.nested = mock.Mock()
        members = []
        output = []
        for ip_ex in six.moves.range(0, 2):
            inst = mock.Mock()
            inst.name = 'ab'[ip_ex]
            inst.FnGetAtt.return_value = '2.1.3.%d' % ip_ex
            output.append('2.1.3.%d' % ip_ex)
            members.append(inst)
        mock_members.return_value = members
        self.assertEqual(output[0], self.group.FnGetAtt('resource.0', 'Bar'))
        self.assertEqual(output[1], self.group.FnGetAtt('resource.1.Bar'))
        self.assertRaises(exception.NotFound,
                          self.group.FnGetAtt, 'resource.2')


def asg_tmpl_with_bad_updt_policy():
    t = template_format.parse(inline_templates.as_heat_template)
    agp = t['resources']['my-group']['properties']
    agp['rolling_updates'] = {"foo": {}}
    return json.dumps(t)


def asg_tmpl_with_default_updt_policy():
    t = template_format.parse(inline_templates.as_heat_template)
    return json.dumps(t)


def asg_tmpl_with_updt_policy(props=None):
    t = template_format.parse(inline_templates.as_heat_template)
    agp = t['resources']['my-group']['properties']
    agp['rolling_updates'] = {
        "min_in_service": 1,
        "max_batch_size": 2,
        "pause_time": 1
    }
    if props is not None:
        agp.update(props)
    return json.dumps(t)


class RollingUpdatePolicyTest(common.HeatTestCase):
    def setUp(self):
        super(RollingUpdatePolicyTest, self).setUp()
        self.stub_keystoneclient(username='test_stack.CfnLBUser')

    def test_parse_without_update_policy(self):
        tmpl = template_format.parse(inline_templates.as_heat_template)
        stack = utils.parse_stack(tmpl)
        stack.validate()
        grp = stack['my-group']
        default_policy = {
            'min_in_service': 0,
            'pause_time': 0,
            'max_batch_size': 1
        }
        self.assertEqual(default_policy, grp.properties['rolling_updates'])

    def test_parse_with_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_updt_policy())
        stack = utils.parse_stack(tmpl)
        stack.validate()
        tmpl_grp = tmpl['resources']['my-group']
        tmpl_policy = tmpl_grp['properties']['rolling_updates']
        tmpl_batch_sz = int(tmpl_policy['max_batch_size'])
        policy = stack['my-group'].properties['rolling_updates']
        self.assertTrue(policy)
        self.assertEqual(3, len(policy))
        self.assertEqual(1, int(policy['min_in_service']))
        self.assertEqual(tmpl_batch_sz, int(policy['max_batch_size']))
        self.assertEqual(1, policy['pause_time'])

    def test_parse_with_default_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_default_updt_policy())
        stack = utils.parse_stack(tmpl)
        stack.validate()
        policy = stack['my-group'].properties['rolling_updates']
        self.assertTrue(policy)
        self.assertEqual(3, len(policy))
        self.assertEqual(0, int(policy['min_in_service']))
        self.assertEqual(1, int(policy['max_batch_size']))
        self.assertEqual(0, policy['pause_time'])

    def test_parse_with_bad_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_bad_updt_policy())
        stack = utils.parse_stack(tmpl)
        error = self.assertRaises(
            exception.StackValidationFailed, stack.validate)
        self.assertIn("foo", six.text_type(error))

    def test_parse_with_bad_pausetime_in_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_default_updt_policy())
        group = tmpl['resources']['my-group']
        group['properties']['rolling_updates'] = {'pause_time': 'a-string'}
        stack = utils.parse_stack(tmpl)
        error = self.assertRaises(
            exception.StackValidationFailed, stack.validate)
        self.assertIn("could not convert string to float",
                      six.text_type(error))


class RollingUpdatePolicyDiffTest(common.HeatTestCase):
    def setUp(self):
        super(RollingUpdatePolicyDiffTest, self).setUp()
        self.stub_keystoneclient(username='test_stack.CfnLBUser')

    def validate_update_policy_diff(self, current, updated):
        # load current stack
        current_tmpl = template_format.parse(current)
        current_stack = utils.parse_stack(current_tmpl)

        # get the json snippet for the current InstanceGroup resource
        current_grp = current_stack['my-group']
        current_snippets = dict((n, r.frozen_definition())
                                for n, r in current_stack.items())
        current_grp_json = current_snippets[current_grp.name]

        # load the updated stack
        updated_tmpl = template_format.parse(updated)
        updated_stack = utils.parse_stack(updated_tmpl)

        # get the updated json snippet for the InstanceGroup resource in the
        # context of the current stack
        updated_grp = updated_stack['my-group']
        updated_grp_json = updated_grp.t.freeze()

        # identify the template difference
        tmpl_diff = updated_grp.update_template_diff(
            updated_grp_json, current_grp_json)
        updated_policy = (updated_grp.properties['rolling_updates']
                          if 'rolling_updates' in updated_grp.properties.data
                          else None)
        self.assertTrue(tmpl_diff.properties_changed())

        current_grp._try_rolling_update = mock.MagicMock()
        current_grp.resize = mock.MagicMock()
        current_grp.handle_update(updated_grp_json, tmpl_diff, None)
        if updated_policy is None:
            self.assertIsNone(
                current_grp.properties.data.get('rolling_updates'))
        else:
            self.assertEqual(updated_policy,
                             current_grp.properties.data['rolling_updates'])

    def test_update_policy_added(self):
        self.validate_update_policy_diff(inline_templates.as_heat_template,
                                         asg_tmpl_with_updt_policy())

    def test_update_policy_updated(self):
        extra_props = {'rolling_updates': {
            'min_in_service': 2,
            'max_batch_size': 4,
            'pause_time': 30}}
        self.validate_update_policy_diff(
            asg_tmpl_with_updt_policy(),
            asg_tmpl_with_updt_policy(props=extra_props))

    def test_update_policy_removed(self):
        self.validate_update_policy_diff(asg_tmpl_with_updt_policy(),
                                         inline_templates.as_heat_template)


class IncorrectUpdatePolicyTest(common.HeatTestCase):
    def setUp(self):
        super(IncorrectUpdatePolicyTest, self).setUp()
        self.stub_keystoneclient(username='test_stack.CfnLBUser')

    def test_with_update_policy_aws(self):
        t = template_format.parse(inline_templates.as_heat_template)
        ag = t['resources']['my-group']
        ag["update_policy"] = {"AutoScalingRollingUpdate": {
            "MinInstancesInService": "1",
            "MaxBatchSize": "2",
            "PauseTime": "PT1S"
        }}
        tmpl = template_format.parse(json.dumps(t))
        stack = utils.parse_stack(tmpl)
        exc = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)
        self.assertIn('Unknown Property AutoScalingRollingUpdate',
                      six.text_type(exc))

    def test_with_update_policy_inst_group(self):
        t = template_format.parse(inline_templates.as_heat_template)
        ag = t['resources']['my-group']
        ag["update_policy"] = {"RollingUpdate": {
            "MinInstancesInService": "1",
            "MaxBatchSize": "2",
            "PauseTime": "PT1S"
        }}
        tmpl = template_format.parse(json.dumps(t))
        stack = utils.parse_stack(tmpl)
        exc = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)
        self.assertIn('Unknown Property RollingUpdate', six.text_type(exc))


class TestCooldownMixin(common.HeatTestCase):
    def setUp(self):
        super(TestCooldownMixin, self).setUp()
        t = template_format.parse(inline_templates.as_heat_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.stack.store()
        self.group = self.stack['my-group']
        self.group.state_set('CREATE', 'COMPLETE')

    def test_cooldown_is_in_progress_toosoon(self):
        cooldown_end = timeutils.utcnow() + datetime.timedelta(seconds=60)
        previous_meta = {'cooldown_end': {
            cooldown_end.isoformat(): 'change_in_capacity : 1'}}
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertRaises(resource.NoActionRequired,
                          self.group._check_scaling_allowed,
                          60)

    def test_cooldown_is_in_progress_toosoon_legacy(self):
        now = timeutils.utcnow()
        previous_meta = {'cooldown': {
            now.isoformat(): 'change_in_capacity : 1'}}
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertRaises(resource.NoActionRequired,
                          self.group._check_scaling_allowed,
                          60)

    def test_cooldown_is_in_progress_scaling_unfinished(self):
        previous_meta = {'scaling_in_progress': True}
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertRaises(resource.NoActionRequired,
                          self.group._check_scaling_allowed,
                          60)

    def test_cooldown_not_in_progress_legacy(self):
        awhile_ago = timeutils.utcnow() - datetime.timedelta(seconds=100)
        previous_meta = {
            'cooldown': {
                awhile_ago.isoformat(): 'change_in_capacity : 1'
            },
            'scaling_in_progress': False
        }
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertIsNone(self.group._check_scaling_allowed(60))

    def test_cooldown_not_in_progress(self):
        awhile_after = timeutils.utcnow() + datetime.timedelta(seconds=60)
        previous_meta = {
            'cooldown_end': {
                awhile_after.isoformat(): 'change_in_capacity : 1'
            },
            'scaling_in_progress': False
        }
        timeutils.set_time_override()
        timeutils.advance_time_seconds(100)
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertIsNone(self.group._check_scaling_allowed(60))
        timeutils.clear_time_override()

    def test_scaling_policy_cooldown_zero(self):
        now = timeutils.utcnow()
        previous_meta = {'cooldown_end': {
            now.isoformat(): 'change_in_capacity : 1'}}
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertIsNone(self.group._check_scaling_allowed(0))

    def test_scaling_policy_cooldown_none(self):
        now = timeutils.utcnow()
        previous_meta = {'cooldown_end': {
            now.isoformat(): 'change_in_capacity : 1'}}
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertIsNone(self.group._check_scaling_allowed(None))

    def test_no_cooldown_no_scaling_in_progress(self):
        # no cooldown entry in the metadata
        awhile_ago = timeutils.utcnow() - datetime.timedelta(seconds=100)
        previous_meta = {'scaling_in_progress': False,
                         awhile_ago.isoformat(): 'change_in_capacity : 1'}
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertIsNone(self.group._check_scaling_allowed(60))

    def test_metadata_is_written(self):
        nowish = timeutils.utcnow()
        reason = 'cool as'
        meta_set = self.patchobject(self.group, 'metadata_set')
        self.patchobject(timeutils, 'utcnow', return_value=nowish)
        self.group._finished_scaling(60, reason)
        cooldown_end = nowish + datetime.timedelta(seconds=60)
        meta_set.assert_called_once_with(
            {'cooldown_end': {cooldown_end.isoformat(): reason},
             'scaling_in_progress': False})

    def test_metadata_is_written_update(self):
        nowish = timeutils.utcnow()
        reason = 'cool as'
        prev_cooldown_end = nowish + datetime.timedelta(seconds=100)
        previous_meta = {
            'cooldown_end': {
                prev_cooldown_end.isoformat(): 'change_in_capacity : 1'
            }
        }
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        meta_set = self.patchobject(self.group, 'metadata_set')
        self.patchobject(timeutils, 'utcnow', return_value=nowish)
        self.group._finished_scaling(60, reason)
        meta_set.assert_called_once_with(
            {'cooldown_end': {prev_cooldown_end.isoformat(): reason},
             'scaling_in_progress': False})
