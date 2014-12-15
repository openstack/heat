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

import logging

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
