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

import mock
import six

from heat.common import exception
from heat.common import grouputils
from heat.common import short_id
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine import resource
from heat.engine.resources.openstack.heat import instance_group as instgrp
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stk_defn
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests import utils


class TestInstanceGroup(common.HeatTestCase):
    def setUp(self):
        super(TestInstanceGroup, self).setUp()
        t = template_format.parse(inline_templates.as_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.defn = rsrc_defn.ResourceDefinition(
            'asg', 'OS::Heat::InstanceGroup',
            {'Size': 2, 'AvailabilityZones': ['zoneb'],
             'LaunchConfigurationName': 'config'})
        self.instance_group = instgrp.InstanceGroup('asg',
                                                    self.defn, self.stack)

    def test_update_timeout(self):
        self.stack.timeout_secs = mock.Mock(return_value=100)
        # there are 3 batches, so we need 2 pauses by 20 sec
        # result timeout should be 100 - 2 * 20 = 60
        self.assertEqual(60, self.instance_group._update_timeout(
            batch_cnt=3, pause_sec=20))

    def test_child_template(self):
        self.instance_group._create_template = mock.Mock(return_value='tpl')
        self.assertEqual('tpl', self.instance_group.child_template())
        self.instance_group._create_template.assert_called_once_with(2)

    def test_child_params(self):
        expected = {'parameters': {},
                    'resource_registry': {
                        'OS::Heat::ScaledResource': 'AWS::EC2::Instance'}}
        self.assertEqual(expected, self.instance_group.child_params())

    def test_tags_default(self):
        expected = [{'Value': u'asg',
                     'Key': 'metering.groupname'}]
        self.assertEqual(expected, self.instance_group._tags())

    def test_tags_with_extra(self):
        self.instance_group.properties.data['Tags'] = [
            {'Key': 'fee', 'Value': 'foo'}]
        expected = [{'Key': 'fee', 'Value': 'foo'},
                    {'Value': u'asg',
                     'Key': 'metering.groupname'}]
        self.assertEqual(expected, self.instance_group._tags())

    def test_tags_with_metering(self):
        self.instance_group.properties.data['Tags'] = [
            {'Key': 'metering.fee', 'Value': 'foo'}]
        expected = [{'Key': 'metering.fee', 'Value': 'foo'}]
        self.assertEqual(expected, self.instance_group._tags())

    def test_validate_launch_conf_ref(self):
        # test the launch conf ref can't be found
        props = self.instance_group.properties.data
        props['LaunchConfigurationName'] = 'JobServerConfig'
        error = self.assertRaises(ValueError, self.instance_group.validate)
        self.assertIn('(JobServerConfig) reference can not be found',
                      six.text_type(error))
        # test resource name of instance group not WebServerGroup, so no ref
        props['LaunchConfigurationName'] = 'LaunchConfig'
        error = self.assertRaises(ValueError, self.instance_group.validate)
        self.assertIn('LaunchConfigurationName (LaunchConfig) requires a '
                      'reference to the configuration not just the '
                      'name of the resource.',
                      six.text_type(error))
        # test validate ok if change instance_group name to 'WebServerGroup'
        self.instance_group.name = 'WebServerGroup'
        self.instance_group.validate()

    def test_handle_create(self):
        self.instance_group.create_with_template = mock.Mock(return_value=None)
        self.instance_group._create_template = mock.Mock(return_value='{}')

        self.instance_group.handle_create()

        self.instance_group._create_template.assert_called_once_with(2)
        self.instance_group.create_with_template.assert_called_once_with('{}')

    def test_update_in_failed(self):
        self.instance_group.state_set('CREATE', 'FAILED')
        # to update the failed instance_group
        self.instance_group.resize = mock.Mock(return_value=None)

        self.instance_group.handle_update(self.defn, None, None)
        self.instance_group.resize.assert_called_once_with(2)

    def test_handle_delete(self):
        self.instance_group.delete_nested = mock.Mock(return_value=None)
        self.instance_group.handle_delete()
        self.instance_group.delete_nested.assert_called_once_with()

    def test_handle_update_size(self):
        self.instance_group._try_rolling_update = mock.Mock(return_value=None)
        self.instance_group.resize = mock.Mock(return_value=None)

        props = {'Size': 5}
        defn = rsrc_defn.ResourceDefinition(
            'nopayload',
            'AWS::AutoScaling::AutoScalingGroup',
            props)

        self.instance_group.handle_update(defn, None, props)
        self.instance_group.resize.assert_called_once_with(5)

    def test_attributes(self):
        get_output = mock.Mock(return_value={'z': '2.1.3.1',
                                             'x': '2.1.3.2',
                                             'c': '2.1.3.3'})
        self.instance_group.get_output = get_output
        inspector = self.instance_group._group_data()
        inspector.member_names = mock.Mock(return_value=['z', 'x', 'c'])
        res = self.instance_group._resolve_attribute('InstanceList')
        self.assertEqual('2.1.3.1,2.1.3.2,2.1.3.3', res)
        get_output.assert_called_once_with('InstanceList')

    def test_attributes_format_fallback(self):
        self.instance_group.get_output = mock.Mock(return_value=['2.1.3.2',
                                                                 '2.1.3.1',
                                                                 '2.1.3.3'])
        mock_members = self.patchobject(grouputils, 'get_members')
        instances = []
        for ip_ex in six.moves.range(1, 4):
            inst = mock.Mock()
            inst.FnGetAtt.return_value = '2.1.3.%d' % ip_ex
            instances.append(inst)
        mock_members.return_value = instances
        res = self.instance_group._resolve_attribute('InstanceList')
        self.assertEqual('2.1.3.1,2.1.3.2,2.1.3.3', res)

    def test_attributes_fallback(self):
        self.instance_group.get_output = mock.Mock(
            side_effect=exception.NotFound)
        mock_members = self.patchobject(grouputils, 'get_members')
        instances = []
        for ip_ex in six.moves.range(1, 4):
            inst = mock.Mock()
            inst.FnGetAtt.return_value = '2.1.3.%d' % ip_ex
            instances.append(inst)
        mock_members.return_value = instances
        res = self.instance_group._resolve_attribute('InstanceList')
        self.assertEqual('2.1.3.1,2.1.3.2,2.1.3.3', res)

    def test_instance_group_refid_rsrc_name(self):
        self.instance_group.id = '123'

        self.instance_group.uuid = '9bfb9456-3fe8-41f4-b318-9dba18eeef74'
        self.instance_group.action = 'CREATE'
        expected = '%s-%s-%s' % (self.instance_group.stack.name,
                                 self.instance_group.name,
                                 short_id.get_id(self.instance_group.uuid))
        self.assertEqual(expected, self.instance_group.FnGetRefId())

    def test_instance_group_refid_rsrc_id(self):
        self.instance_group.resource_id = 'phy-rsrc-id'
        self.assertEqual('phy-rsrc-id', self.instance_group.FnGetRefId())


class TestLaunchConfig(common.HeatTestCase):
    def create_resource(self, t, stack, resource_name):
        # subsequent resources may need to reference previous created resources
        # use the stack's resource objects instead of instantiating new ones
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_update_metadata_replace(self):
        """Updating the config's metadata causes a config replacement."""
        lc_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Resources": {
    "JobServerConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Metadata": {"foo": "bar"},
      "Properties": {
        "ImageId"           : "foo",
        "InstanceType"      : "m1.large",
        "KeyName"           : "test",
      }
    }
  }
}
'''
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_KeypairConstraint_validate()

        t = template_format.parse(lc_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'JobServerConfig')
        props = copy.copy(rsrc.properties.data)
        metadata = copy.copy(rsrc.metadata_get())
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props,
                                                      metadata)
        # Change nothing in the first update
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual('bar', metadata['foo'])
        metadata['foo'] = 'wibble'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props,
                                                      metadata)
        # Changing metadata in the second update triggers UpdateReplace
        updater = scheduler.TaskRunner(rsrc.update, update_snippet)
        self.assertRaises(resource.UpdateReplace, updater)


class LoadbalancerReloadTest(common.HeatTestCase):
    def test_Instances(self):
        t = template_format.parse(inline_templates.as_template)
        stack = utils.parse_stack(t)
        lb = stack['ElasticLoadBalancer']
        lb.update = mock.Mock(return_value=None)

        defn = rsrc_defn.ResourceDefinition(
            'asg', 'OS::Heat::InstanceGroup',
            {'Size': 2,
             'AvailabilityZones': ['zoneb'],
             "LaunchConfigurationName": "LaunchConfig",
             "LoadBalancerNames": ["ElasticLoadBalancer"]})
        group = instgrp.InstanceGroup('asg', defn, stack)

        mocks = self.setup_mocks(group, ['aaaa', 'bbb'])
        expected = rsrc_defn.ResourceDefinition(
            'ElasticLoadBalancer',
            'AWS::ElasticLoadBalancing::LoadBalancer',
            {'Instances': ['aaaa', 'bbb'],
             'Listeners': [{'InstancePort': u'80',
                            'LoadBalancerPort': u'80',
                            'Protocol': 'HTTP'}],
             'AvailabilityZones': ['nova']}
        )

        group._lb_reload()
        self.check_mocks(group, mocks)
        lb.update.assert_called_once_with(expected)

    def test_members(self):
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

        t = template_format.parse(inline_templates.as_template)
        t['Resources']['ElasticLoadBalancer'] = {
            'Type': 'OS::Neutron::LoadBalancer',
            'Properties': {
                'protocol_port': 8080,
            }
        }
        stack = utils.parse_stack(t)

        lb = stack['ElasticLoadBalancer']
        lb.update = mock.Mock(return_value=None)

        defn = rsrc_defn.ResourceDefinition(
            'asg', 'OS::Heat::InstanceGroup',
            {'Size': 2,
             'AvailabilityZones': ['zoneb'],
             "LaunchConfigurationName": "LaunchConfig",
             "LoadBalancerNames": ["ElasticLoadBalancer"]})
        group = instgrp.InstanceGroup('asg', defn, stack)

        mocks = self.setup_mocks(group, ['aaaa', 'bbb'])
        expected = rsrc_defn.ResourceDefinition(
            'ElasticLoadBalancer',
            'OS::Neutron::LoadBalancer',
            {'protocol_port': 8080,
             'members': ['aaaa', 'bbb']})

        group._lb_reload()
        self.check_mocks(group, mocks)
        lb.update.assert_called_once_with(expected)

    def test_lb_reload_invalid_resource(self):
        t = template_format.parse(inline_templates.as_template)
        t['Resources']['ElasticLoadBalancer'] = {
            'Type': 'AWS::EC2::Volume',
            'Properties': {
                'AvailabilityZone': 'nova'
            }
        }
        stack = utils.parse_stack(t)

        lb = stack['ElasticLoadBalancer']
        lb.update = mock.Mock(return_value=None)

        defn = rsrc_defn.ResourceDefinition(
            'asg', 'OS::Heat::InstanceGroup',
            {'Size': 2,
             'AvailabilityZones': ['zoneb'],
             "LaunchConfigurationName": "LaunchConfig",
             "LoadBalancerNames": ["ElasticLoadBalancer"]})
        group = instgrp.InstanceGroup('asg', defn, stack)

        self.setup_mocks(group, ['aaaa', 'bbb'])
        error = self.assertRaises(exception.Error,
                                  group._lb_reload)
        self.assertEqual(
            "Unsupported resource 'ElasticLoadBalancer' in "
            "LoadBalancerNames",
            six.text_type(error))

    def test_lb_reload_static_resolve(self):
        t = template_format.parse(inline_templates.as_template)
        properties = t['Resources']['ElasticLoadBalancer']['Properties']
        properties['AvailabilityZones'] = {'Fn::GetAZs': ''}

        self.patchobject(stk_defn.StackDefinition, 'get_availability_zones',
                         return_value=['abc', 'xyz'])

        stack = utils.parse_stack(t, params=inline_templates.as_params)
        lb = stack['ElasticLoadBalancer']
        lb.state_set(lb.CREATE, lb.COMPLETE)
        lb.handle_update = mock.Mock(return_value=None)
        group = stack['WebServerGroup']
        self.setup_mocks(group, ['aaaabbbbcccc'])
        group._lb_reload()
        lb.handle_update.assert_called_once_with(
            mock.ANY, mock.ANY,
            {'Instances': ['aaaabbbbcccc']})

    def setup_mocks(self, group, member_refids):
        refs = {str(i): r for i, r in enumerate(member_refids)}
        group.get_output = mock.Mock(return_value=refs)
        names = sorted(refs.keys())
        group_data = group._group_data()
        group_data.member_names = mock.Mock(return_value=names)
        group._group_data = mock.Mock(return_value=group_data)

    def check_mocks(self, group, unused):
        pass


class LoadbalancerReloadFallbackTest(LoadbalancerReloadTest):
    def setup_mocks(self, group, member_refids):
        # Raise NotFound when getting output, to force fallback to old-school
        # grouputils functions
        group.get_output = mock.Mock(side_effect=exception.NotFound)

        def make_mock_member(refid):
            mem = mock.Mock()
            mem.FnGetRefId = mock.Mock(return_value=refid)
            return mem

        members = [make_mock_member(r) for r in member_refids]
        mock_members = self.patchobject(grouputils, 'get_members',
                                        return_value=members)
        return mock_members

    def check_mocks(self, group, mock_members):
        mock_members.assert_called_once_with(group)


class InstanceGroupWithNestedStack(common.HeatTestCase):
    def setUp(self):
        super(InstanceGroupWithNestedStack, self).setUp()
        t = template_format.parse(inline_templates.as_template)
        self.stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.create_launch_config(t, self.stack)
        wsg_props = self.stack['WebServerGroup'].t._properties
        self.defn = rsrc_defn.ResourceDefinition(
            'asg', 'OS::Heat::InstanceGroup',
            {'Size': 2, 'AvailabilityZones': ['zoneb'],
             'LaunchConfigurationName': wsg_props['LaunchConfigurationName']})
        self.group = instgrp.InstanceGroup('asg', self.defn, self.stack)

        self.group._lb_reload = mock.Mock()
        self.group.update_with_template = mock.Mock()
        self.group.check_update_complete = mock.Mock()

    def create_launch_config(self, t, stack):
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        rsrc = stack['LaunchConfig']
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def get_fake_nested_stack(self, size=1):
        tmpl = '''
        heat_template_version: 2013-05-23
        description: AutoScaling Test
        resources:
        '''
        resource = '''
          r%(i)d:
            type: ResourceWithPropsAndAttrs
            properties:
              Foo: bar%(i)d
          '''
        resources = '\n'.join([resource % {'i': i + 1} for i in range(size)])
        nested_t = tmpl + resources
        return utils.parse_stack(template_format.parse(nested_t))


class ReplaceTest(InstanceGroupWithNestedStack):
    scenarios = [
        ('1', dict(min_in_service=0, batch_size=1, updates=2)),
        ('2', dict(min_in_service=0, batch_size=2, updates=1)),
        ('3', dict(min_in_service=3, batch_size=1, updates=3)),
        ('4', dict(min_in_service=3, batch_size=2, updates=2))]

    def setUp(self):
        super(ReplaceTest, self).setUp()
        nested = self.get_fake_nested_stack(2)
        inspector = self.group._group_data()
        inspector.size = mock.Mock(return_value=2)
        inspector.template = mock.Mock(return_value=nested.defn._template)

    def test_rolling_updates(self):
        self.group._replace(self.min_in_service, self.batch_size, 0)
        self.assertEqual(self.updates,
                         len(self.group.update_with_template.call_args_list))
        self.assertEqual(self.updates + 1,
                         len(self.group._lb_reload.call_args_list))


class ResizeWithFailedInstancesTest(InstanceGroupWithNestedStack):
    scenarios = [
        ('1', dict(size=3, failed=['r1'], content={'r2', 'r3', 'r4'})),
        ('2', dict(size=3, failed=['r4'], content={'r1', 'r2', 'r3'})),
        ('3', dict(size=2, failed=['r1', 'r2'], content={'r3', 'r4'})),
        ('4', dict(size=2, failed=['r3', 'r4'], content={'r1', 'r2'})),
        ('5', dict(size=2, failed=['r2', 'r3'], content={'r1', 'r4'})),
        ('6', dict(size=3, failed=['r2', 'r3'], content={'r1', 'r3', 'r4'}))]

    def setUp(self):
        super(ResizeWithFailedInstancesTest, self).setUp()
        nested = self.get_fake_nested_stack(4)

        inspector = mock.Mock(spec=grouputils.GroupInspector)
        self.patchobject(grouputils.GroupInspector, 'from_parent_resource',
                         return_value=inspector)
        inspector.member_names.return_value = (self.failed +
                                               sorted(self.content -
                                                      set(self.failed)))
        inspector.template.return_value = nested.defn._template

    def test_resize(self):
        self.group.resize(self.size)
        tmpl = self.group.update_with_template.call_args[0][0]
        resources = tmpl.resource_definitions(None)
        self.assertEqual(self.content, set(resources.keys()))


class TestGetBatches(common.HeatTestCase):

    scenarios = [
        ('4_1_0', dict(curr_cap=4, bat_size=1, min_serv=0,
                       batches=[(4, 1)] * 4)),
        ('4_1_4', dict(curr_cap=4, bat_size=1, min_serv=4,
                       batches=([(5, 1)] * 4) + [(4, 0)])),
        ('4_1_5', dict(curr_cap=4, bat_size=1, min_serv=5,
                       batches=([(5, 1)] * 4) + [(4, 0)])),
        ('4_2_0', dict(curr_cap=4, bat_size=2, min_serv=0,
                       batches=[(4, 2)] * 2)),
        ('4_2_4', dict(curr_cap=4, bat_size=2, min_serv=4,
                       batches=([(6, 2)] * 2) + [(4, 0)])),
        ('5_2_0', dict(curr_cap=5, bat_size=2, min_serv=0,
                       batches=([(5, 2)] * 2) + [(5, 1)])),
        ('5_2_4', dict(curr_cap=5, bat_size=2, min_serv=4,
                       batches=([(6, 2)] * 2) + [(5, 1)])),
        ('3_2_0', dict(curr_cap=3, bat_size=2, min_serv=0,
                       batches=[(3, 2), (3, 1)])),
        ('3_2_4', dict(curr_cap=3, bat_size=2, min_serv=4,
                       batches=[(5, 2), (4, 1), (3, 0)])),
        ('4_4_0', dict(curr_cap=4, bat_size=4, min_serv=0,
                       batches=[(4, 4)])),
        ('4_5_0', dict(curr_cap=4, bat_size=5, min_serv=0,
                       batches=[(4, 4)])),
        ('4_4_1', dict(curr_cap=4, bat_size=4, min_serv=1,
                       batches=[(5, 4), (4, 0)])),
        ('4_6_1', dict(curr_cap=4, bat_size=6, min_serv=1,
                       batches=[(5, 4), (4, 0)])),
        ('4_4_2', dict(curr_cap=4, bat_size=4, min_serv=2,
                       batches=[(6, 4), (4, 0)])),
        ('4_4_4', dict(curr_cap=4, bat_size=4, min_serv=4,
                       batches=[(8, 4), (4, 0)])),
        ('4_5_6', dict(curr_cap=4, bat_size=5, min_serv=6,
                       batches=[(8, 4), (4, 0)])),
    ]

    def test_get_batches(self):
        batches = list(instgrp.InstanceGroup._get_batches(self.curr_cap,
                                                          self.bat_size,
                                                          self.min_serv))
        self.assertEqual(self.batches, batches)
