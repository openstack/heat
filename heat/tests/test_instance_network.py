
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

import uuid

from heat.common import template_format
from heat.engine import clients
from heat.engine import environment
from heat.engine import parser
from heat.engine.resources import instance as instances
from heat.engine.resources import network_interface as network_interfaces
from heat.engine.resources import nova_utils
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes


wp_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    },
    "InstanceType": {
      "Type": "String",
      "Description": "EC2 instance type",
      "Default": "m1.small",
      "AllowedValues": [ "m1.small", "m1.large" ]
    },
    "SubnetId": {
      "Type" : "String",
      "Description" : "SubnetId of an existing subnet in your VPC"
    },
  },
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId"        : "F17-x86_64-gold",
        "InstanceType"   : { "Ref" : "InstanceType" },
        "SubnetId"       : { "Ref" : "SubnetId" },
        "KeyName"        : { "Ref" : "KeyName" },
        "UserData"       : "wordpress"
      }
    }
  }
}
'''


wp_template_with_nic = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    },
    "InstanceType": {
      "Type": "String",
      "Description": "EC2 instance type",
      "Default": "m1.small",
      "AllowedValues": [ "m1.small", "m1.large" ]
    },
    "SubnetId": {
      "Type" : "String",
      "Description" : "SubnetId of an existing subnet in your VPC"
    },
  },
  "Resources" : {

    "nic1": {
        "Type": "AWS::EC2::NetworkInterface",
        "Properties": {
            "SubnetId": { "Ref": "SubnetId" }
        }
    },

    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId"        : "F17-x86_64-gold",
        "InstanceType"   : { "Ref" : "InstanceType" },
        "NetworkInterfaces": [ { "NetworkInterfaceId" : {"Ref": "nic1"},
                                 "DeviceIndex" : "0"  } ],
        "KeyName"        : { "Ref" : "KeyName" },
        "UserData"       : "wordpress"
      }
    }
  }
}
'''


class FakeNeutron(object):

    def show_subnet(self, subnet, **_params):
        return {
            'subnet': {
                'name': 'name',
                'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'allocation_pools': [{'start': '10.10.0.2',
                                      'end': '10.10.0.254'}],
                'gateway_ip': '10.10.0.1',
                'ip_version': 4,
                'cidr': '10.10.0.0/24',
                'id': '4156c7a5-e8c4-4aff-a6e1-8f3c7bc83861',
                'enable_dhcp': False,
            }}

    def create_port(self, body=None):
        return {
            'port': {
                'admin_state_up': True,
                'device_id': '',
                'device_owner': '',
                'fixed_ips': [{
                    'ip_address': '10.0.3.3',
                    'subnet_id': '4156c7a5-e8c4-4aff-a6e1-8f3c7bc83861'}],
                'id': '64d913c1-bcb1-42d2-8f0a-9593dbcaf251',
                'mac_address': 'fa:16:3e:25:32:5d',
                'name': '',
                'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                'status': 'ACTIVE',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f'
            }}


class instancesTest(HeatTestCase):
    def setUp(self):
        super(instancesTest, self).setUp()
        self.fc = fakes.FakeClient()
        utils.setup_dummy_db()

    def _create_test_instance(self, return_server, name):
        stack_name = '%s_s' % name
        t = template_format.parse(wp_template)
        template = parser.Template(t)
        kwargs = {'KeyName': 'test',
                  'InstanceType': 'm1.large',
                  'SubnetId': '4156c7a5-e8c4-4aff-a6e1-8f3c7bc83861'}
        stack = parser.Stack(utils.dummy_context(), stack_name, template,
                             environment.Environment(kwargs),
                             stack_id=str(uuid.uuid4()))

        t['Resources']['WebServer']['Properties']['ImageId'] = 'CentOS 5.2'
        instance = instances.Instance('%s_name' % name,
                                      t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(instance, 'nova')
        instance.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        self.m.StubOutWithMock(instance, 'neutron')
        instance.neutron().MultipleTimes().AndReturn(FakeNeutron())

        instance.t = instance.stack.resolve_runtime_data(instance.t)

        # need to resolve the template functions
        server_userdata = nova_utils.build_userdata(
            instance,
            instance.t['Properties']['UserData'],
            'ec2-user')
        self.m.StubOutWithMock(nova_utils, 'build_userdata')
        nova_utils.build_userdata(
            instance,
            instance.t['Properties']['UserData'],
            'ec2-user').AndReturn(server_userdata)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, instance.name),
            security_groups=None,
            userdata=server_userdata, scheduler_hints=None, meta=None,
            nics=[{'port-id': '64d913c1-bcb1-42d2-8f0a-9593dbcaf251'}],
            availability_zone=None).AndReturn(
                return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        return instance

    def _create_test_instance_with_nic(self, return_server, name):
        stack_name = '%s_s' % name
        t = template_format.parse(wp_template_with_nic)
        template = parser.Template(t)
        kwargs = {'KeyName': 'test',
                  'InstanceType': 'm1.large',
                  'SubnetId': '4156c7a5-e8c4-4aff-a6e1-8f3c7bc83861'}
        stack = parser.Stack(utils.dummy_context(), stack_name, template,
                             environment.Environment(kwargs),
                             stack_id=str(uuid.uuid4()))

        t['Resources']['WebServer']['Properties']['ImageId'] = 'CentOS 5.2'

        nic = network_interfaces.NetworkInterface('%s_nic' % name,
                                                  t['Resources']['nic1'],
                                                  stack)

        instance = instances.Instance('%s_name' % name,
                                      t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(nic, 'neutron')
        nic.neutron().MultipleTimes().AndReturn(FakeNeutron())

        self.m.StubOutWithMock(instance, 'nova')
        instance.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        nic.t = nic.stack.resolve_runtime_data(nic.t)
        instance.t = instance.stack.resolve_runtime_data(instance.t)

        # need to resolve the template functions
        server_userdata = nova_utils.build_userdata(
            instance,
            instance.t['Properties']['UserData'],
            'ec2-user')
        self.m.StubOutWithMock(nova_utils, 'build_userdata')
        nova_utils.build_userdata(
            instance,
            instance.t['Properties']['UserData'],
            'ec2-user').AndReturn(server_userdata)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, instance.name),
            security_groups=None,
            userdata=server_userdata, scheduler_hints=None, meta=None,
            nics=[{'port-id': '64d913c1-bcb1-42d2-8f0a-9593dbcaf251'}],
            availability_zone=None).AndReturn(
                return_server)
        self.m.ReplayAll()

        # create network interface
        scheduler.TaskRunner(nic.create)()
        stack["nic1"] = nic

        scheduler.TaskRunner(instance.create)()
        return instance

    def test_instance_create(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_create')
        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        expected_ip = return_server.networks['public'][0]
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))

        self.m.VerifyAll()

    def test_instance_create_with_nic(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance_with_nic(
            return_server, 'in_create_wnic')

        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        expected_ip = return_server.networks['public'][0]
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))

        self.m.VerifyAll()
