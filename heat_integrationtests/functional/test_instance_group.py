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
import logging
import yaml

from heatclient import exc

from heat_integrationtests.common import test


LOG = logging.getLogger(__name__)


class InstanceGroupTest(test.HeatIntegrationTest):

    template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create multiple instances.",
  "Parameters" : {"size": {"Type": "String", "Default": "1"},
                  "AZ": {"Type": "String", "Default": "nova"},
                  "image": {"Type": "String"},
                  "flavor": {"Type": "String"},
                  "keyname": {"Type": "String"}},
  "Resources": {
    "JobServerGroup": {
      "Type": "OS::Heat::InstanceGroup",
      "Properties": {
        "LaunchConfigurationName" : {"Ref": "JobServerConfig"},
        "Size" : {"Ref": "size"},
        "AvailabilityZones" : [{"Ref": "AZ"}]
      }
    },

    "JobServerConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Metadata": {"foo": "bar"},
      "Properties": {
        "ImageId"           : {"Ref": "image"},
        "InstanceType"      : {"Ref": "flavor"},
        "KeyName"           : {"Ref": "keyname"},
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : "jsconfig data",
      }
    }
  },
  "Outputs": {
    "InstanceList": {"Value": {
      "Fn::GetAtt": ["JobServerGroup", "InstanceList"]}}
  }
}
'''

    instance_template = '''
heat_template_version: 2013-05-23
parameters:
  ImageId: {type: string}
  InstanceType: {type: string}
  KeyName: {type: string}
  SecurityGroups: {type: comma_delimited_list}
  UserData: {type: string}
  Tags: {type: comma_delimited_list}

resources:
  random1:
    type: OS::Heat::RandomString

outputs:
  PublicIp:
    value: {get_attr: [random1, value]}
'''

    # This is designed to fail.
    bad_instance_template = '''
heat_template_version: 2013-05-23
parameters:
  ImageId: {type: string}
  InstanceType: {type: string}
  KeyName: {type: string}
  SecurityGroups: {type: comma_delimited_list}
  UserData: {type: string}
  Tags: {type: comma_delimited_list}

resources:
  random1:
    type: OS::Heat::RandomString
    depends_on: waiter
  ready_poster:
    type: AWS::CloudFormation::WaitConditionHandle
  waiter:
    type: AWS::CloudFormation::WaitCondition
    properties:
      Handle: {Ref: ready_poster}
      Timeout: 1
outputs:
  PublicIp:
    value: {get_attr: [random1, value]}
'''

    def setUp(self):
        super(InstanceGroupTest, self).setUp()
        self.client = self.orchestration_client
        if not self.conf.image_ref:
            raise self.skipException("No image configured to test")
        if not self.conf.keypair_name:
            raise self.skipException("No keyname configured to test")
        if not self.conf.instance_type:
            raise self.skipException("No flavor configured to test")

    def assert_instance_count(self, stack, expected_count):
        inst_list = self._stack_output(stack, 'InstanceList')
        self.assertEqual(expected_count, len(inst_list.split(',')))

    def _get_nested_identifier(self, stack_identifier):
        rsrc = self.client.resources.get(stack_identifier, 'JobServerGroup')
        nested_link = [l for l in rsrc.links if l['rel'] == 'nested']
        self.assertEqual(1, len(nested_link))
        nested_href = nested_link[0]['href']
        nested_id = nested_href.split('/')[-1]
        nested_identifier = '/'.join(nested_href.split('/')[-2:])
        physical_resource_id = rsrc.physical_resource_id
        self.assertEqual(physical_resource_id, nested_id)
        return nested_identifier

    def _assert_instance_state(self, nested_identifier,
                               num_complete, num_failed):
        for res in self.client.resources.list(nested_identifier):
            if 'COMPLETE' in res.resource_status:
                num_complete = num_complete - 1
            elif 'FAILED' in res.resource_status:
                num_failed = num_failed - 1
        self.assertEqual(0, num_failed)
        self.assertEqual(0, num_complete)

    def test_basic_create_works(self):
        """Make sure the working case is good.
        Note this combines test_override_aws_ec2_instance into this test as
        well, which is:
        If AWS::EC2::Instance is overridden, InstanceGroup will automatically
        use that overridden resource type.
        """

        files = {'provider.yaml': self.instance_template}
        env = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': 4,
                              'image': self.conf.image_ref,
                              'keyname': self.conf.keypair_name,
                              'flavor': self.conf.instance_type}}
        stack_identifier = self.stack_create(template=self.template,
                                             files=files, environment=env)
        initial_resources = {
            'JobServerConfig': 'AWS::AutoScaling::LaunchConfiguration',
            'JobServerGroup': 'OS::Heat::InstanceGroup'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        stack = self.client.stacks.get(stack_identifier)
        self.assert_instance_count(stack, 4)

    def test_create_config_prop_validation(self):
        """Make sure that during a group create the instance
        properties are validated. And an error causes the group to fail.
        """
        stack_name = self._stack_rand_name()

        # add a property without a default and don't provide a value.
        # we use this to make the instance fail on a property validation
        # error.
        broken = yaml.load(copy.copy(self.instance_template))
        broken['parameters']['no_default'] = {'type': 'string'}
        files = {'provider.yaml': yaml.dump(broken)}
        env = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': 4,
                              'image': self.conf.image_ref,
                              'keyname': self.conf.keypair_name,
                              'flavor': self.conf.instance_type}}

        # now with static nested stack validation, this gets raised quickly.
        excp = self.assertRaises(exc.HTTPBadRequest, self.client.stacks.create,
                                 stack_name=stack_name, template=self.template,
                                 files=files, disable_rollback=True,
                                 parameters={}, environment=env)
        self.assertIn('Property no_default not assigned', str(excp))

    def test_size_updates_work(self):
        files = {'provider.yaml': self.instance_template}
        env = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': 2,
                              'image': self.conf.image_ref,
                              'keyname': self.conf.keypair_name,
                              'flavor': self.conf.instance_type}}

        stack_identifier = self.stack_create(template=self.template,
                                             files=files,
                                             environment=env)
        stack = self.client.stacks.get(stack_identifier)
        self.assert_instance_count(stack, 2)

        # Increase min size to 5
        env2 = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
                'parameters': {'size': 5,
                               'image': self.conf.image_ref,
                               'keyname': self.conf.keypair_name,
                               'flavor': self.conf.instance_type}}
        self.update_stack(stack_identifier, self.template,
                          environment=env2, files=files)
        self._wait_for_stack_status(stack_identifier, 'UPDATE_COMPLETE')
        stack = self.client.stacks.get(stack_identifier)
        self.assert_instance_count(stack, 5)

    def test_update_group_replace(self):
        """Make sure that during a group update the non updatable
        properties cause a replacement.
        """
        files = {'provider.yaml': self.instance_template}
        env = {'resource_registry':
               {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': 1,
                              'image': self.conf.image_ref,
                              'keyname': self.conf.keypair_name,
                              'flavor': self.conf.instance_type}}

        stack_identifier = self.stack_create(template=self.template,
                                             files=files,
                                             environment=env)
        rsrc = self.client.resources.get(stack_identifier, 'JobServerGroup')
        orig_asg_id = rsrc.physical_resource_id

        env2 = {'resource_registry':
                {'AWS::EC2::Instance': 'provider.yaml'},
                'parameters': {'size': '2',
                               'AZ': 'wibble',
                               'image': self.conf.image_ref,
                               'keyname': self.conf.keypair_name,
                               'flavor': self.conf.instance_type}}
        self.update_stack(stack_identifier, self.template,
                          environment=env2, files=files)

        # replacement will cause the resource physical_resource_id to change.
        rsrc = self.client.resources.get(stack_identifier, 'JobServerGroup')
        self.assertNotEqual(orig_asg_id, rsrc.physical_resource_id)

    def test_create_instance_error_causes_group_error(self):
        """If a resource in an instance group fails to be created, the instance
        group itself will fail and the broken inner resource will remain.
        """
        stack_name = self._stack_rand_name()
        files = {'provider.yaml': self.bad_instance_template}
        env = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': 2,
                              'image': self.conf.image_ref,
                              'keyname': self.conf.keypair_name,
                              'flavor': self.conf.instance_type}}

        self.client.stacks.create(
            stack_name=stack_name,
            template=self.template,
            files=files,
            disable_rollback=True,
            parameters={},
            environment=env
        )
        self.addCleanup(self.client.stacks.delete, stack_name)
        stack = self.client.stacks.get(stack_name)
        stack_identifier = '%s/%s' % (stack_name, stack.id)
        self._wait_for_stack_status(stack_identifier, 'CREATE_FAILED')
        initial_resources = {
            'JobServerConfig': 'AWS::AutoScaling::LaunchConfiguration',
            'JobServerGroup': 'OS::Heat::InstanceGroup'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        nested_ident = self._get_nested_identifier(stack_identifier)
        self._assert_instance_state(nested_ident, 0, 2)

    def test_update_instance_error_causes_group_error(self):
        """If a resource in an instance group fails to be created during an
        update, the instance group itself will fail and the broken inner
        resource will remain.
        """
        files = {'provider.yaml': self.instance_template}
        env = {'resource_registry': {'AWS::EC2::Instance': 'provider.yaml'},
               'parameters': {'size': 2,
                              'image': self.conf.image_ref,
                              'keyname': self.conf.keypair_name,
                              'flavor': self.conf.instance_type}}

        stack_identifier = self.stack_create(template=self.template,
                                             files=files,
                                             environment=env)
        initial_resources = {
            'JobServerConfig': 'AWS::AutoScaling::LaunchConfiguration',
            'JobServerGroup': 'OS::Heat::InstanceGroup'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        stack = self.client.stacks.get(stack_identifier)
        self.assert_instance_count(stack, 2)
        nested_ident = self._get_nested_identifier(stack_identifier)
        self._assert_instance_state(nested_ident, 2, 0)

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
        nested_ident = self._get_nested_identifier(stack_identifier)
        self._assert_instance_state(nested_ident, 0, 3)
