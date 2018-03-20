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
import json

import mock
from oslo_utils import timeutils
import six

from heat.common import exception
from heat.common import grouputils
from heat.common import template_format
from heat.engine.clients.os import nova
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


as_template = inline_templates.as_template


class TestAutoScalingGroupValidation(common.HeatTestCase):
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
        self.stub_SnapshotConstraint_validate()
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.assertRaises(exception.NotSupported,
                          self.validate_scaling_group, t,
                          stack, 'WebServerGroup')

    def test_invalid_min_size(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '-1'
        properties['MaxSize'] = '2'

        stack = utils.parse_stack(t, params=inline_templates.as_params)

        self.stub_SnapshotConstraint_validate()
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "The size of AutoScalingGroup can not be less than zero"
        self.assertEqual(expected_msg, six.text_type(e))

    def test_invalid_max_size(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '3'
        properties['MaxSize'] = '1'

        stack = utils.parse_stack(t, params=inline_templates.as_params)

        self.stub_SnapshotConstraint_validate()
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "MinSize can not be greater than MaxSize"
        self.assertEqual(expected_msg, six.text_type(e))

    def test_invalid_desiredcapacity(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        properties['DesiredCapacity'] = '4'

        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.stub_SnapshotConstraint_validate()
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "DesiredCapacity must be between MinSize and MaxSize"
        self.assertEqual(expected_msg, six.text_type(e))

    def test_invalid_desiredcapacity_zero(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        properties['DesiredCapacity'] = '0'

        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.stub_SnapshotConstraint_validate()
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "DesiredCapacity must be between MinSize and MaxSize"
        self.assertEqual(expected_msg, six.text_type(e))

    def test_validate_without_InstanceId_and_LaunchConfigurationName(self):
        t = template_format.parse(as_template)
        agp = t['Resources']['WebServerGroup']['Properties']
        agp.pop('LaunchConfigurationName')
        agp.pop('LoadBalancerNames')
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        rsrc = stack['WebServerGroup']
        error_msg = ("Either 'InstanceId' or 'LaunchConfigurationName' "
                     "must be provided.")
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn(error_msg, six.text_type(exc))

    def test_validate_with_InstanceId_and_LaunchConfigurationName(self):
        t = template_format.parse(as_template)
        agp = t['Resources']['WebServerGroup']['Properties']
        agp['InstanceId'] = '5678'
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        rsrc = stack['WebServerGroup']
        error_msg = ("Either 'InstanceId' or 'LaunchConfigurationName' "
                     "must be provided.")
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn(error_msg, six.text_type(exc))

    def _stub_nova_server_get(self, not_found=False):
        mock_server = mock.MagicMock()
        mock_server.image = {'id': 'dd619705-468a-4f7d-8a06-b84794b3561a'}
        mock_server.flavor = {'id': '1'}
        mock_server.key_name = 'test'
        mock_server.security_groups = [{u'name': u'hth_test'}]
        if not_found:
            self.patchobject(nova.NovaClientPlugin, 'get_server',
                             side_effect=exception.EntityNotFound(
                                 entity='Server', name='5678'))
        else:
            self.patchobject(nova.NovaClientPlugin, 'get_server',
                             return_value=mock_server)

    def test_scaling_group_create_with_instanceid(self):
        t = template_format.parse(as_template)
        agp = t['Resources']['WebServerGroup']['Properties']
        agp['InstanceId'] = '5678'
        agp.pop('LaunchConfigurationName')
        agp.pop('LoadBalancerNames')
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        rsrc = stack['WebServerGroup']

        self._stub_nova_server_get()

        _config, ins_props = rsrc._get_conf_properties()

        self.assertEqual('dd619705-468a-4f7d-8a06-b84794b3561a',
                         ins_props['ImageId'])
        self.assertEqual('test', ins_props['KeyName'])
        self.assertEqual(['hth_test'], ins_props['SecurityGroups'])
        self.assertEqual('1', ins_props['InstanceType'])

    def test_scaling_group_create_with_instanceid_not_found(self):
        t = template_format.parse(as_template)
        agp = t['Resources']['WebServerGroup']['Properties']
        agp.pop('LaunchConfigurationName')
        agp['InstanceId'] = '5678'
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        rsrc = stack['WebServerGroup']
        self._stub_nova_server_get(not_found=True)
        msg = ("Property error: "
               "Resources.WebServerGroup.Properties.InstanceId: "
               "Error validating value '5678': The Server (5678) could "
               "not be found.")
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn(msg, six.text_type(exc))


class TestScalingGroupTags(common.HeatTestCase):
    def setUp(self):
        super(TestScalingGroupTags, self).setUp()
        t = template_format.parse(as_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = self.stack['WebServerGroup']

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

        t = template_format.parse(as_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = self.stack['WebServerGroup']
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.assertIsNone(self.group.validate())

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

    def test_scaling_update_in_progress(self):
        """Don't resize when update in progress"""
        self.group.state_set('UPDATE', 'IN_PROGRESS')
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
                groupname=u'WebServerGroup',
                message=u'Start resizing the group WebServerGroup',
                adjustment=33,
                stack=self.group.stack),
            mock.call(
                capacity=3, suffix='end',
                adjustment_type='PercentChangeInCapacity',
                groupname=u'WebServerGroup',
                message=u'End resizing the group WebServerGroup',
                adjustment=33,
                stack=self.group.stack)]

        self.assertEqual(expected_notifies, notify.call_args_list)
        resize.assert_called_once_with(3)
        finished_scaling.assert_called_once_with(
            None,
            'PercentChangeInCapacity : 33',
            size_changed=True)

    def test_scale_down_min_adjustment(self):
        self.patchobject(grouputils, 'get_size', return_value=5)
        resize = self.patchobject(self.group, 'resize')
        finished_scaling = self.patchobject(self.group, '_finished_scaling')
        notify = self.patch('heat.engine.notification.autoscaling.send')
        self.patchobject(self.group, '_check_scaling_allowed')
        self.group.adjust(-33, adjustment_type='PercentChangeInCapacity',
                          min_adjustment_step=2)

        expected_notifies = [
            mock.call(
                capacity=5, suffix='start',
                adjustment_type='PercentChangeInCapacity',
                groupname=u'WebServerGroup',
                message=u'Start resizing the group WebServerGroup',
                adjustment=-33,
                stack=self.group.stack),
            mock.call(
                capacity=3, suffix='end',
                adjustment_type='PercentChangeInCapacity',
                groupname=u'WebServerGroup',
                message=u'End resizing the group WebServerGroup',
                adjustment=-33,
                stack=self.group.stack)]

        self.assertEqual(expected_notifies, notify.call_args_list)
        resize.assert_called_once_with(3)
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
                groupname=u'WebServerGroup',
                message=u'Start resizing the group WebServerGroup',
                adjustment=5,
                stack=self.group.stack),
            mock.call(
                capacity=4, suffix='error',
                adjustment_type='ExactCapacity',
                groupname=u'WebServerGroup',
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
        t = template_format.parse(as_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.group = self.stack['WebServerGroup']
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
        props = {'DesiredCapacity': 4,
                 'MinSize': 0,
                 'MaxSize': 6}
        self.group._get_new_capacity = mock.Mock(return_value=4)
        defn = rsrc_defn.ResourceDefinition(
            'nopayload',
            'AWS::AutoScaling::AutoScalingGroup',
            props)

        self.group.handle_update(defn, None, props)
        self.group.resize.assert_called_once_with(4)
        self.group._try_rolling_update.assert_called_once_with(props)

    def test_handle_update_desired_nocap(self):
        self.group._try_rolling_update = mock.Mock(return_value=None)
        self.group.resize = mock.Mock(return_value=None)
        get_size = self.patchobject(grouputils, 'get_size')
        get_size.return_value = 4

        props = {'MinSize': 0,
                 'MaxSize': 6}
        defn = rsrc_defn.ResourceDefinition(
            'nopayload',
            'AWS::AutoScaling::AutoScalingGroup',
            props)

        self.group.handle_update(defn, None, props)
        self.group.resize.assert_called_once_with(4)
        self.group._try_rolling_update.assert_called_once_with(props)

    def test_conf_properties_vpc_zone(self):
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_SnapshotConstraint_validate()

        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['VPCZoneIdentifier'] = ['xxxx']

        stack = utils.parse_stack(t, params=inline_templates.as_params)
        # create the launch configuration resource
        conf = stack['LaunchConfig']
        self.assertIsNone(conf.validate())
        scheduler.TaskRunner(conf.create)()
        self.assertEqual((conf.CREATE, conf.COMPLETE), conf.state)

        group = stack['WebServerGroup']
        config, props = group._get_conf_properties()
        self.assertEqual('xxxx', props['SubnetId'])
        conf.delete()

    def test_update_in_failed(self):
        self.group.state_set('CREATE', 'FAILED')
        # to update the failed asg
        self.group.resize = mock.Mock(return_value=None)

        new_defn = rsrc_defn.ResourceDefinition(
            'asg', 'AWS::AutoScaling::AutoScalingGroup',
            {'AvailabilityZones': ['nova'],
             'LaunchConfigurationName': 'config',
             'MaxSize': 5,
             'MinSize': 1,
             'DesiredCapacity': 2})

        self.group.handle_update(new_defn, None, None)
        self.group.resize.assert_called_once_with(2)


def asg_tmpl_with_bad_updt_policy():
    t = template_format.parse(inline_templates.as_template)
    ag = t['Resources']['WebServerGroup']
    ag["UpdatePolicy"] = {"foo": {}}
    return json.dumps(t)


def asg_tmpl_with_default_updt_policy():
    t = template_format.parse(inline_templates.as_template)
    ag = t['Resources']['WebServerGroup']
    ag["UpdatePolicy"] = {"AutoScalingRollingUpdate": {}}
    return json.dumps(t)


def asg_tmpl_with_updt_policy():
    t = template_format.parse(inline_templates.as_template)
    ag = t['Resources']['WebServerGroup']
    ag["UpdatePolicy"] = {"AutoScalingRollingUpdate": {
        "MinInstancesInService": "1",
        "MaxBatchSize": "2",
        "PauseTime": "PT1S"
    }}
    return json.dumps(t)


class RollingUpdatePolicyTest(common.HeatTestCase):
    def setUp(self):
        super(RollingUpdatePolicyTest, self).setUp()
        self.fc = fakes_nova.FakeClient()
        self.stub_keystoneclient(username='test_stack.CfnLBUser')
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_SnapshotConstraint_validate()

    def test_parse_without_update_policy(self):
        tmpl = template_format.parse(inline_templates.as_template)
        stack = utils.parse_stack(tmpl, params=inline_templates.as_params)

        stack.validate()
        grp = stack['WebServerGroup']
        self.assertFalse(grp.update_policy['AutoScalingRollingUpdate'])

    def test_parse_with_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_updt_policy())
        stack = utils.parse_stack(tmpl, params=inline_templates.as_params)

        stack.validate()
        tmpl_grp = tmpl['Resources']['WebServerGroup']
        tmpl_policy = tmpl_grp['UpdatePolicy']['AutoScalingRollingUpdate']
        tmpl_batch_sz = int(tmpl_policy['MaxBatchSize'])
        grp = stack['WebServerGroup']
        self.assertTrue(grp.update_policy)
        self.assertEqual(1, len(grp.update_policy))
        self.assertIn('AutoScalingRollingUpdate', grp.update_policy)
        policy = grp.update_policy['AutoScalingRollingUpdate']
        self.assertIsNotNone(policy)
        self.assertGreater(len(policy), 0)
        self.assertEqual(1, int(policy['MinInstancesInService']))
        self.assertEqual(tmpl_batch_sz, int(policy['MaxBatchSize']))
        self.assertEqual('PT1S', policy['PauseTime'])

    def test_parse_with_default_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_default_updt_policy())
        stack = utils.parse_stack(tmpl, params=inline_templates.as_params)

        stack.validate()
        grp = stack['WebServerGroup']
        self.assertTrue(grp.update_policy)
        self.assertEqual(1, len(grp.update_policy))
        self.assertIn('AutoScalingRollingUpdate', grp.update_policy)
        policy = grp.update_policy['AutoScalingRollingUpdate']
        self.assertIsNotNone(policy)
        self.assertGreater(len(policy), 0)
        self.assertEqual(0, int(policy['MinInstancesInService']))
        self.assertEqual(1, int(policy['MaxBatchSize']))
        self.assertEqual('PT0S', policy['PauseTime'])

    def test_parse_with_bad_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_bad_updt_policy())
        stack = utils.parse_stack(tmpl, params=inline_templates.as_params)
        error = self.assertRaises(
            exception.StackValidationFailed, stack.validate)
        self.assertIn("foo", six.text_type(error))

    def test_parse_with_bad_pausetime_in_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_default_updt_policy())
        group = tmpl['Resources']['WebServerGroup']
        policy = group['UpdatePolicy']['AutoScalingRollingUpdate']
        policy['PauseTime'] = 'P1YT1H'
        stack = utils.parse_stack(tmpl, params=inline_templates.as_params)
        error = self.assertRaises(
            exception.StackValidationFailed, stack.validate)
        self.assertIn("Only ISO 8601 duration format", six.text_type(error))


class RollingUpdatePolicyDiffTest(common.HeatTestCase):
    def setUp(self):
        super(RollingUpdatePolicyDiffTest, self).setUp()
        self.fc = fakes_nova.FakeClient()
        self.stub_keystoneclient(username='test_stack.CfnLBUser')

    def validate_update_policy_diff(self, current, updated):
        # load current stack
        current_tmpl = template_format.parse(current)
        current_stack = utils.parse_stack(current_tmpl,
                                          params=inline_templates.as_params)

        # get the json snippet for the current InstanceGroup resource
        current_grp = current_stack['WebServerGroup']
        current_snippets = dict((n, r.frozen_definition())
                                for n, r in current_stack.items())
        current_grp_json = current_snippets[current_grp.name]

        # load the updated stack
        updated_tmpl = template_format.parse(updated)
        updated_stack = utils.parse_stack(updated_tmpl,
                                          params=inline_templates.as_params)

        # get the updated json snippet for the InstanceGroup resource in the
        # context of the current stack
        updated_grp = updated_stack['WebServerGroup']
        updated_grp_json = updated_grp.t.freeze()

        # identify the template difference
        tmpl_diff = updated_grp.update_template_diff(
            updated_grp_json, current_grp_json)
        self.assertTrue(tmpl_diff.update_policy_changed())

        # test application of the new update policy in handle_update
        current_grp._try_rolling_update = mock.MagicMock()
        current_grp.resize = mock.MagicMock()
        current_grp.handle_update(updated_grp_json, tmpl_diff, None)
        self.assertEqual(updated_grp_json._update_policy or {},
                         current_grp.update_policy.data)

    def test_update_policy_added(self):
        self.validate_update_policy_diff(inline_templates.as_template,
                                         asg_tmpl_with_updt_policy())

    def test_update_policy_updated(self):
        updt_template = json.loads(asg_tmpl_with_updt_policy())
        grp = updt_template['Resources']['WebServerGroup']
        policy = grp['UpdatePolicy']['AutoScalingRollingUpdate']
        policy['MinInstancesInService'] = '2'
        policy['MaxBatchSize'] = '4'
        policy['PauseTime'] = 'PT1M30S'
        self.validate_update_policy_diff(asg_tmpl_with_updt_policy(),
                                         json.dumps(updt_template))

    def test_update_policy_removed(self):
        self.validate_update_policy_diff(asg_tmpl_with_updt_policy(),
                                         inline_templates.as_template)


class TestCooldownMixin(common.HeatTestCase):
    def setUp(self):
        super(TestCooldownMixin, self).setUp()
        t = template_format.parse(inline_templates.as_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.stack.store()
        self.group = self.stack['WebServerGroup']
        self.group.state_set('CREATE', 'COMPLETE')

    def test_cooldown_is_in_progress_toosoon(self):
        cooldown_end = timeutils.utcnow() + datetime.timedelta(seconds=60)
        previous_meta = {'cooldown_end': {
            cooldown_end.isoformat(): 'ChangeInCapacity : 1'}}
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertRaises(resource.NoActionRequired,
                          self.group._check_scaling_allowed,
                          60)

    def test_cooldown_is_in_progress_toosoon_legacy(self):
        now = timeutils.utcnow()
        previous_meta = {'cooldown': {
            now.isoformat(): 'ChangeInCapacity : 1'}}
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

    def test_scaling_not_in_progress_legacy(self):
        awhile_ago = timeutils.utcnow() - datetime.timedelta(seconds=100)
        previous_meta = {
            'cooldown': {
                awhile_ago.isoformat(): 'ChangeInCapacity : 1'
            },
            'scaling_in_progress': False
        }
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertIsNone(self.group._check_scaling_allowed(60))

    def test_scaling_not_in_progress(self):
        awhile_after = timeutils.utcnow() + datetime.timedelta(seconds=60)
        previous_meta = {
            'cooldown_end': {
                awhile_after.isoformat(): 'ChangeInCapacity : 1'
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
        previous_meta = {
            'cooldown_end': {
                now.isoformat(): 'ChangeInCapacity : 1'
            },
            'scaling_in_progress': False
        }
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertIsNone(self.group._check_scaling_allowed(60))

    def test_scaling_policy_cooldown_none(self):
        now = timeutils.utcnow()
        previous_meta = {
            'cooldown_end': {
                now.isoformat(): 'ChangeInCapacity : 1'
            },
            'scaling_in_progress': False
        }
        self.patchobject(self.group, 'metadata_get',
                         return_value=previous_meta)
        self.assertIsNone(self.group._check_scaling_allowed(None))

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
                prev_cooldown_end.isoformat(): 'ChangeInCapacity : 1'
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
