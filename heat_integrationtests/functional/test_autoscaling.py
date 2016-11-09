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
import json

from heatclient import exc
from oslo_log import log as logging
import six
from testtools import matchers

from heat_integrationtests.common import test
from heat_integrationtests.functional import functional_base


LOG = logging.getLogger(__name__)


class AutoscalingGroupTest(functional_base.FunctionalTestsBase):

    template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create multiple instances.",
  "Parameters" : {"size": {"Type": "String", "Default": "1"},
                  "AZ": {"Type": "String", "Default": "nova"},
                  "image": {"Type": "String"},
                  "flavor": {"Type": "String"},
                  "user_data": {"Type": "String", "Default": "jsconfig data"}},
  "Resources": {
    "JobServerGroup": {
      "Type" : "AWS::AutoScaling::AutoScalingGroup",
      "Properties" : {
        "AvailabilityZones" : [{"Ref": "AZ"}],
        "LaunchConfigurationName" : { "Ref" : "JobServerConfig" },
        "MinSize" : {"Ref": "size"},
        "MaxSize" : "20"
      }
    },

    "JobServerConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Metadata": {"foo": "bar"},
      "Properties": {
        "ImageId"           : {"Ref": "image"},
        "InstanceType"      : {"Ref": "flavor"},
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : {"Ref": "user_data"}
      }
    }
  },
  "Outputs": {
    "InstanceList": {"Value": {
      "Fn::GetAtt": ["JobServerGroup", "InstanceList"]}},
    "JobServerConfigRef": {"Value": {
      "Ref": "JobServerConfig"}}
  }
}
'''

    instance_template = '''
heat_template_version: 2013-05-23
parameters:
  ImageId: {type: string}
  InstanceType: {type: string}
  SecurityGroups: {type: comma_delimited_list}
  UserData: {type: string}
  Tags: {type: comma_delimited_list, default: "x,y"}

resources:
  random1:
    type: OS::Heat::RandomString
    properties:
      salt: {get_param: UserData}
outputs:
  PublicIp: {value: {get_attr: [random1, value]}}
  AvailabilityZone: {value: 'not-used11'}
  PrivateDnsName: {value: 'not-used12'}
  PublicDnsName: {value: 'not-used13'}
  PrivateIp: {value: 'not-used14'}
'''

    # This is designed to fail.
    bad_instance_template = '''
heat_template_version: 2013-05-23
parameters:
  ImageId: {type: string}
  InstanceType: {type: string}
  SecurityGroups: {type: comma_delimited_list}
  UserData: {type: string}
  Tags: {type: comma_delimited_list, default: "x,y"}

resources:
  random1:
    type: OS::Heat::RandomString
    depends_on: waiter
  ready_poster:
    type: AWS::CloudFormation::WaitConditionHandle
  waiter:
    type: AWS::CloudFormation::WaitCondition
    properties:
      Handle: {get_resource: ready_poster}
      Timeout: 1
outputs:
  PublicIp:
    value: {get_attr: [random1, value]}
'''

    def setUp(self):
        super(AutoscalingGroupTest, self).setUp()
        if not self.conf.minimal_image_ref:
            raise self.skipException("No minimal image configured to test")
        if not self.conf.instance_type:
            raise self.skipException("No flavor configured to test")

    def assert_instance_count(self, stack, expected_count):
        inst_list = self._stack_output(stack, 'InstanceList')
        self.assertEqual(expected_count, len(inst_list.split(',')))

    def _assert_instance_state(self, nested_identifier,
                               num_complete, num_failed):
        for res in self.client.resources.list(nested_identifier):
            if 'COMPLETE' in res.resource_status:
                num_complete = num_complete - 1
            elif 'FAILED' in res.resource_status:
                num_failed = num_failed - 1
        self.assertEqual(0, num_failed)
        self.assertEqual(0, num_complete)


class AutoscalingGroupBasicTest(AutoscalingGroupTest):

    def test_basic_create_works(self):
        """Make sure the working case is good.

        Note this combines test_override_aws_ec2_instance into this test as
        well, which is:
        If AWS::EC2::Instance is overridden, AutoScalingGroup will
        automatically use that overridden resource type.
        """

        files = {'provider.yaml': self.instance_template}
        env = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': 4,
                              'image': self.conf.minimal_image_ref,
                              'flavor': self.conf.instance_type}}
        stack_identifier = self.stack_create(template=self.template,
                                             files=files, environment=env)
        initial_resources = {
            'JobServerConfig': 'AWS::AutoScaling::LaunchConfiguration',
            'JobServerGroup': 'AWS::AutoScaling::AutoScalingGroup'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        stack = self.client.stacks.get(stack_identifier)
        self.assert_instance_count(stack, 4)

    def test_size_updates_work(self):
        files = {'provider.yaml': self.instance_template}
        env = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': 2,
                              'image': self.conf.minimal_image_ref,
                              'flavor': self.conf.instance_type}}

        stack_identifier = self.stack_create(template=self.template,
                                             files=files,
                                             environment=env)
        stack = self.client.stacks.get(stack_identifier)
        self.assert_instance_count(stack, 2)

        # Increase min size to 5
        env2 = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
                'parameters': {'size': 5,
                               'image': self.conf.minimal_image_ref,
                               'flavor': self.conf.instance_type}}
        self.update_stack(stack_identifier, self.template,
                          environment=env2, files=files)
        stack = self.client.stacks.get(stack_identifier)
        self.assert_instance_count(stack, 5)

    def test_update_group_replace(self):
        """Test case for ensuring non-updatable props case a replacement.

        Make sure that during a group update the non-updatable
        properties cause a replacement.
        """
        files = {'provider.yaml': self.instance_template}
        env = {'resource_registry':
               {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': '1',
                              'image': self.conf.minimal_image_ref,
                              'flavor': self.conf.instance_type}}

        stack_identifier = self.stack_create(template=self.template,
                                             files=files,
                                             environment=env)
        rsrc = self.client.resources.get(stack_identifier, 'JobServerGroup')
        orig_asg_id = rsrc.physical_resource_id

        env2 = {'resource_registry':
                {'AWS::EC2::Instance': 'provider.yaml'},
                'parameters': {'size': '1',
                               'AZ': 'wibble',
                               'image': self.conf.minimal_image_ref,
                               'flavor': self.conf.instance_type,
                               'user_data': 'new data'}}
        self.update_stack(stack_identifier, self.template,
                          environment=env2, files=files)

        # replacement will cause the resource physical_resource_id to change.
        rsrc = self.client.resources.get(stack_identifier, 'JobServerGroup')
        self.assertNotEqual(orig_asg_id, rsrc.physical_resource_id)

    def test_create_instance_error_causes_group_error(self):
        """Test create failing a resource in the instance group.

        If a resource in an instance group fails to be created, the instance
        group itself will fail and the broken inner resource will remain.
        """
        stack_name = self._stack_rand_name()
        files = {'provider.yaml': self.bad_instance_template}
        env = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': 2,
                              'image': self.conf.minimal_image_ref,
                              'flavor': self.conf.instance_type}}

        self.client.stacks.create(
            stack_name=stack_name,
            template=self.template,
            files=files,
            disable_rollback=True,
            parameters={},
            environment=env
        )
        self.addCleanup(self._stack_delete, stack_name)
        stack = self.client.stacks.get(stack_name)
        stack_identifier = '%s/%s' % (stack_name, stack.id)
        self._wait_for_stack_status(stack_identifier, 'CREATE_FAILED')
        initial_resources = {
            'JobServerConfig': 'AWS::AutoScaling::LaunchConfiguration',
            'JobServerGroup': 'AWS::AutoScaling::AutoScalingGroup'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        nested_ident = self.assert_resource_is_a_stack(stack_identifier,
                                                       'JobServerGroup')
        self._assert_instance_state(nested_ident, 0, 2)

    def test_update_instance_error_causes_group_error(self):
        """Test update failing a resource in the instance group.

        If a resource in an instance group fails to be created during an
        update, the instance group itself will fail and the broken inner
        resource will remain.
        """
        files = {'provider.yaml': self.instance_template}
        env = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': 2,
                              'image': self.conf.minimal_image_ref,
                              'flavor': self.conf.instance_type}}

        stack_identifier = self.stack_create(template=self.template,
                                             files=files,
                                             environment=env)
        initial_resources = {
            'JobServerConfig': 'AWS::AutoScaling::LaunchConfiguration',
            'JobServerGroup': 'AWS::AutoScaling::AutoScalingGroup'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        stack = self.client.stacks.get(stack_identifier)
        self.assert_instance_count(stack, 2)
        nested_ident = self.assert_resource_is_a_stack(stack_identifier,
                                                       'JobServerGroup')
        self._assert_instance_state(nested_ident, 2, 0)
        initial_list = [res.resource_name
                        for res in self.client.resources.list(nested_ident)]

        env['parameters']['size'] = 3
        files2 = {'provider.yaml': self.bad_instance_template}
        self.client.stacks.update(
            stack_id=stack_identifier,
            template=self.template,
            files=files2,
            disable_rollback=True,
            parameters={},
            environment=env
        )
        self._wait_for_stack_status(stack_identifier, 'UPDATE_FAILED')

        # assert that there are 3 bad instances
        nested_ident = self.assert_resource_is_a_stack(stack_identifier,
                                                       'JobServerGroup')

        # 2 resources should be in update failed, and one create failed.
        for res in self.client.resources.list(nested_ident):
            if res.resource_name in initial_list:
                self._wait_for_resource_status(nested_ident,
                                               res.resource_name,
                                               'UPDATE_FAILED')
            else:
                self._wait_for_resource_status(nested_ident,
                                               res.resource_name,
                                               'CREATE_FAILED')

    def test_group_suspend_resume(self):

        files = {'provider.yaml': self.instance_template}
        env = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': 4,
                              'image': self.conf.minimal_image_ref,
                              'flavor': self.conf.instance_type}}
        stack_identifier = self.stack_create(template=self.template,
                                             files=files, environment=env)

        nested_ident = self.assert_resource_is_a_stack(stack_identifier,
                                                       'JobServerGroup')

        self.stack_suspend(stack_identifier)
        self._wait_for_all_resource_status(nested_ident, 'SUSPEND_COMPLETE')

        self.stack_resume(stack_identifier)
        self._wait_for_all_resource_status(nested_ident, 'RESUME_COMPLETE')


class AutoscalingGroupUpdatePolicyTest(AutoscalingGroupTest):

    def ig_tmpl_with_updt_policy(self):
        templ = json.loads(copy.deepcopy(self.template))
        up = {"AutoScalingRollingUpdate": {
            "MinInstancesInService": "1",
            "MaxBatchSize": "2",
            "PauseTime": "PT1S"}}
        templ['Resources']['JobServerGroup']['UpdatePolicy'] = up
        return templ

    def update_instance_group(self, updt_template,
                              num_updates_expected_on_updt,
                              num_creates_expected_on_updt,
                              num_deletes_expected_on_updt):

        # setup stack from the initial template
        files = {'provider.yaml': self.instance_template}
        size = 10
        env = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': size,
                              'image': self.conf.minimal_image_ref,
                              'flavor': self.conf.instance_type}}
        stack_name = self._stack_rand_name()
        stack_identifier = self.stack_create(
            stack_name=stack_name,
            template=self.ig_tmpl_with_updt_policy(),
            files=files,
            environment=env)
        stack = self.client.stacks.get(stack_identifier)
        nested_ident = self.assert_resource_is_a_stack(stack_identifier,
                                                       'JobServerGroup')

        # test that physical resource name of launch configuration is used
        conf_name = self._stack_output(stack, 'JobServerConfigRef')
        conf_name_pattern = '%s-JobServerConfig-[a-zA-Z0-9]+$' % stack_name
        self.assertThat(conf_name,
                        matchers.MatchesRegex(conf_name_pattern))

        # test the number of instances created
        self.assert_instance_count(stack, size)
        # saves info from initial list of instances for comparison later
        init_instances = self.client.resources.list(nested_ident)
        init_names = [inst.resource_name for inst in init_instances]

        # test stack update
        self.update_stack(stack_identifier, updt_template,
                          environment=env, files=files)
        updt_stack = self.client.stacks.get(stack_identifier)

        # test that the launch configuration is replaced
        updt_conf_name = self._stack_output(updt_stack, 'JobServerConfigRef')
        self.assertThat(updt_conf_name,
                        matchers.MatchesRegex(conf_name_pattern))
        self.assertNotEqual(conf_name, updt_conf_name)

        # test that the group size are the same
        updt_instances = self.client.resources.list(nested_ident)
        updt_names = [inst.resource_name for inst in updt_instances]
        self.assertEqual(len(init_names), len(updt_names))
        for res in updt_instances:
            self.assertEqual('UPDATE_COMPLETE', res.resource_status)

        # test that the appropriate number of instance names are the same
        matched_names = set(updt_names) & set(init_names)
        self.assertEqual(num_updates_expected_on_updt, len(matched_names))

        # test that the appropriate number of new instances are created
        self.assertEqual(num_creates_expected_on_updt,
                         len(set(updt_names) - set(init_names)))

        # test that the appropriate number of instances are deleted
        self.assertEqual(num_deletes_expected_on_updt,
                         len(set(init_names) - set(updt_names)))

        # test that the older instances are the ones being deleted
        if num_deletes_expected_on_updt > 0:
            deletes_expected = init_names[:num_deletes_expected_on_updt]
            self.assertNotIn(deletes_expected, updt_names)

    def test_instance_group_update_replace(self):
        """Test simple update replace.

        Test update replace with no conflict in batch size and minimum
        instances in service.
        """
        updt_template = self.ig_tmpl_with_updt_policy()
        grp = updt_template['Resources']['JobServerGroup']
        policy = grp['UpdatePolicy']['AutoScalingRollingUpdate']
        policy['MinInstancesInService'] = '1'
        policy['MaxBatchSize'] = '3'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['UserData'] = 'new data'

        self.update_instance_group(updt_template,
                                   num_updates_expected_on_updt=10,
                                   num_creates_expected_on_updt=0,
                                   num_deletes_expected_on_updt=0)

    def test_instance_group_update_replace_with_adjusted_capacity(self):
        """Test update replace with capacity adjustment.

        Test update replace with capacity adjustment due to conflict in batch
        size and minimum instances in service.
        """
        updt_template = self.ig_tmpl_with_updt_policy()
        grp = updt_template['Resources']['JobServerGroup']
        policy = grp['UpdatePolicy']['AutoScalingRollingUpdate']
        policy['MinInstancesInService'] = '8'
        policy['MaxBatchSize'] = '4'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['UserData'] = 'new data'

        self.update_instance_group(updt_template,
                                   num_updates_expected_on_updt=8,
                                   num_creates_expected_on_updt=2,
                                   num_deletes_expected_on_updt=2)

    def test_instance_group_update_replace_huge_batch_size(self):
        """Test update replace with a huge batch size."""
        updt_template = self.ig_tmpl_with_updt_policy()
        group = updt_template['Resources']['JobServerGroup']
        policy = group['UpdatePolicy']['AutoScalingRollingUpdate']
        policy['MinInstancesInService'] = '0'
        policy['MaxBatchSize'] = '20'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['UserData'] = 'new data'

        self.update_instance_group(updt_template,
                                   num_updates_expected_on_updt=10,
                                   num_creates_expected_on_updt=0,
                                   num_deletes_expected_on_updt=0)

    def test_instance_group_update_replace_huge_min_in_service(self):
        """Update replace with huge number of minimum instances in service."""
        updt_template = self.ig_tmpl_with_updt_policy()
        group = updt_template['Resources']['JobServerGroup']
        policy = group['UpdatePolicy']['AutoScalingRollingUpdate']
        policy['MinInstancesInService'] = '20'
        policy['MaxBatchSize'] = '1'
        policy['PauseTime'] = 'PT0S'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['UserData'] = 'new data'

        self.update_instance_group(updt_template,
                                   num_updates_expected_on_updt=9,
                                   num_creates_expected_on_updt=1,
                                   num_deletes_expected_on_updt=1)

    def test_instance_group_update_no_replace(self):
        """Test simple update only and no replace.

        Test simple update only and no replace (i.e. updated instance flavor
        in Launch Configuration) with no conflict in batch size and
        minimum instances in service.
        """
        updt_template = self.ig_tmpl_with_updt_policy()
        group = updt_template['Resources']['JobServerGroup']
        policy = group['UpdatePolicy']['AutoScalingRollingUpdate']
        policy['MinInstancesInService'] = '1'
        policy['MaxBatchSize'] = '3'
        policy['PauseTime'] = 'PT0S'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['InstanceType'] = self.conf.minimal_instance_type

        self.update_instance_group(updt_template,
                                   num_updates_expected_on_updt=10,
                                   num_creates_expected_on_updt=0,
                                   num_deletes_expected_on_updt=0)

    def test_instance_group_update_no_replace_with_adjusted_capacity(self):
        """Test update only and no replace with capacity adjustment.

        Test update only and no replace (i.e. updated instance flavor in
        Launch Configuration) with capacity adjustment due to conflict in
        batch size and minimum instances in service.
        """
        updt_template = self.ig_tmpl_with_updt_policy()
        group = updt_template['Resources']['JobServerGroup']
        policy = group['UpdatePolicy']['AutoScalingRollingUpdate']
        policy['MinInstancesInService'] = '8'
        policy['MaxBatchSize'] = '4'
        policy['PauseTime'] = 'PT0S'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['InstanceType'] = self.conf.minimal_instance_type

        self.update_instance_group(updt_template,
                                   num_updates_expected_on_updt=8,
                                   num_creates_expected_on_updt=2,
                                   num_deletes_expected_on_updt=2)


class AutoScalingSignalTest(AutoscalingGroupTest):

    template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create multiple instances.",
  "Parameters" : {"size": {"Type": "String", "Default": "1"},
                  "AZ": {"Type": "String", "Default": "nova"},
                  "image": {"Type": "String"},
                  "flavor": {"Type": "String"}},
  "Resources": {
    "custom_lb": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId": {"Ref": "image"},
        "InstanceType": {"Ref": "flavor"},
        "UserData": "foo",
        "SecurityGroups": [ "sg-1" ],
        "Tags": []
      },
      "Metadata": {
        "IPs": {"Fn::GetAtt": ["JobServerGroup", "InstanceList"]}
      }
    },
    "JobServerGroup": {
      "Type" : "AWS::AutoScaling::AutoScalingGroup",
      "Properties" : {
        "AvailabilityZones" : [{"Ref": "AZ"}],
        "LaunchConfigurationName" : { "Ref" : "JobServerConfig" },
        "DesiredCapacity" : {"Ref": "size"},
        "MinSize" : "0",
        "MaxSize" : "20"
      }
    },
    "JobServerConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Metadata": {"foo": "bar"},
      "Properties": {
        "ImageId"           : {"Ref": "image"},
        "InstanceType"      : {"Ref": "flavor"},
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : "jsconfig data"
      }
    },
    "ScaleUpPolicy" : {
      "Type" : "AWS::AutoScaling::ScalingPolicy",
      "Properties" : {
        "AdjustmentType" : "ChangeInCapacity",
        "AutoScalingGroupName" : { "Ref" : "JobServerGroup" },
        "Cooldown" : "0",
        "ScalingAdjustment": "1"
      }
    },
    "ScaleDownPolicy" : {
      "Type" : "AWS::AutoScaling::ScalingPolicy",
      "Properties" : {
        "AdjustmentType" : "ChangeInCapacity",
        "AutoScalingGroupName" : { "Ref" : "JobServerGroup" },
        "Cooldown" : "0",
        "ScalingAdjustment" : "-2"
      }
    }
  },
  "Outputs": {
    "InstanceList": {"Value": {
      "Fn::GetAtt": ["JobServerGroup", "InstanceList"]}}
  }
}
'''

    lb_template = '''
heat_template_version: 2013-05-23
parameters:
  ImageId: {type: string}
  InstanceType: {type: string}
  SecurityGroups: {type: comma_delimited_list}
  UserData: {type: string}
  Tags: {type: comma_delimited_list, default: "x,y"}

resources:
outputs:
  PublicIp: {value: "not-used"}
  AvailabilityZone: {value: 'not-used1'}
  PrivateDnsName: {value: 'not-used2'}
  PublicDnsName: {value: 'not-used3'}
  PrivateIp: {value: 'not-used4'}

'''

    def setUp(self):
        super(AutoScalingSignalTest, self).setUp()
        self.build_timeout = self.conf.build_timeout
        self.build_interval = self.conf.build_interval
        self.files = {'provider.yaml': self.instance_template,
                      'lb.yaml': self.lb_template}
        self.env = {'resource_registry':
                    {'resources':
                     {'custom_lb': {'AWS::EC2::Instance': 'lb.yaml'}},
                     'AWS::EC2::Instance': 'provider.yaml'},
                    'parameters': {'size': 2,
                                   'image': self.conf.minimal_image_ref,
                                   'flavor': self.conf.instance_type}}

    def check_instance_count(self, stack_identifier, expected):
        md = self.client.resources.metadata(stack_identifier, 'custom_lb')
        actual_md = len(md['IPs'].split(','))
        if actual_md != expected:
            LOG.warning('check_instance_count exp:%d, meta:%s' % (expected,
                                                                  md['IPs']))
            return False

        stack = self.client.stacks.get(stack_identifier)
        inst_list = self._stack_output(stack, 'InstanceList')
        actual = len(inst_list.split(','))
        if actual != expected:
            LOG.warning('check_instance_count exp:%d, act:%s' % (expected,
                                                                 inst_list))
        return actual == expected

    def test_scaling_meta_update(self):
        """Use heatclient to signal the up and down policy.

        Then confirm that the metadata in the custom_lb is updated each
        time.
        """
        stack_identifier = self.stack_create(template=self.template,
                                             files=self.files,
                                             environment=self.env)

        self.assertTrue(test.call_until_true(
            self.build_timeout, self.build_interval,
            self.check_instance_count, stack_identifier, 2))

        nested_ident = self.assert_resource_is_a_stack(stack_identifier,
                                                       'JobServerGroup')
        # Scale up one, Trigger alarm
        self.client.resources.signal(stack_identifier, 'ScaleUpPolicy')
        self._wait_for_stack_status(nested_ident, 'UPDATE_COMPLETE')
        self.assertTrue(test.call_until_true(
            self.build_timeout, self.build_interval,
            self.check_instance_count, stack_identifier, 3))

        # Scale down two, Trigger alarm
        self.client.resources.signal(stack_identifier, 'ScaleDownPolicy')
        self._wait_for_stack_status(nested_ident, 'UPDATE_COMPLETE')
        self.assertTrue(test.call_until_true(
            self.build_timeout, self.build_interval,
            self.check_instance_count, stack_identifier, 1))

    def test_signal_with_policy_update(self):
        """Prove that an updated policy is used in the next signal."""

        stack_identifier = self.stack_create(template=self.template,
                                             files=self.files,
                                             environment=self.env)

        self.assertTrue(test.call_until_true(
            self.build_timeout, self.build_interval,
            self.check_instance_count, stack_identifier, 2))

        nested_ident = self.assert_resource_is_a_stack(stack_identifier,
                                                       'JobServerGroup')
        # Scale up one, Trigger alarm
        self.client.resources.signal(stack_identifier, 'ScaleUpPolicy')
        self._wait_for_stack_status(nested_ident, 'UPDATE_COMPLETE')
        self.assertTrue(test.call_until_true(
            self.build_timeout, self.build_interval,
            self.check_instance_count, stack_identifier, 3))

        # increase the adjustment to "+2" and remove the DesiredCapacity
        # so we don't go from 3 to 2.
        new_template = self.template.replace(
            '"ScalingAdjustment": "1"',
            '"ScalingAdjustment": "2"').replace(
                '"DesiredCapacity" : {"Ref": "size"},', '')

        self.update_stack(stack_identifier, template=new_template,
                          environment=self.env, files=self.files)

        # Scale up two, Trigger alarm
        self.client.resources.signal(stack_identifier, 'ScaleUpPolicy')
        self._wait_for_stack_status(nested_ident, 'UPDATE_COMPLETE')
        self.assertTrue(test.call_until_true(
            self.build_timeout, self.build_interval,
            self.check_instance_count, stack_identifier, 5))

    def test_signal_during_suspend(self):
        """Prove that a signal will fail when the stack is in suspend."""

        stack_identifier = self.stack_create(template=self.template,
                                             files=self.files,
                                             environment=self.env)

        self.assertTrue(test.call_until_true(
            self.build_timeout, self.build_interval,
            self.check_instance_count, stack_identifier, 2))

        nested_ident = self.assert_resource_is_a_stack(stack_identifier,
                                                       'JobServerGroup')

        # suspend the top level stack.
        self.client.actions.suspend(stack_id=stack_identifier)

        # Wait for stack to reach SUSPEND_COMPLETE
        self._wait_for_stack_status(stack_identifier, 'SUSPEND_COMPLETE')

        # Send a signal and an exception will raise
        ex = self.assertRaises(exc.BadRequest,
                               self.client.resources.signal,
                               stack_identifier, 'ScaleUpPolicy')

        error_msg = 'Signal resource during SUSPEND is not supported'
        self.assertIn(error_msg, six.text_type(ex))
        ev = self.wait_for_event_with_reason(
            stack_identifier,
            reason='Cannot signal resource during SUSPEND',
            rsrc_name='ScaleUpPolicy')
        self.assertEqual('SUSPEND_COMPLETE', ev[0].resource_status)

        # still SUSPEND_COMPLETE (not gone to UPDATE_COMPLETE)
        self._wait_for_stack_status(nested_ident, 'SUSPEND_COMPLETE')
        self._wait_for_stack_status(stack_identifier, 'SUSPEND_COMPLETE')
        # still 2 instances.
        self.assertTrue(test.call_until_true(
            self.build_timeout, self.build_interval,
            self.check_instance_count, stack_identifier, 2))
