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
import uuid

from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import neutron
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine.resources.aws.ec2 import instance as instances
from heat.engine.resources.aws.ec2 import network_interface as net_interfaces
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils

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

    def delete_port(self, port_id):
        return None


class instancesTest(common.HeatTestCase):
    def setUp(self):
        super(instancesTest, self).setUp()
        self.fc = fakes_nova.FakeClient()

    def _mock_get_image_id_success(self, imageId_input, imageId):
        self.m_f_i = self.patchobject(glance.GlanceClientPlugin,
                                      'find_image_by_name_or_id',
                                      return_value=imageId)

    def _test_instance_create_delete(self, vm_status='ACTIVE',
                                     vm_delete_status='NotFound'):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server, 'in_create')

        instance.resource_id = '1234'
        instance.status = vm_status
        # this makes sure the auto increment worked on instance creation
        self.assertGreater(instance.id, 0)

        expected_ip = return_server.networks['public'][0]
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicDnsName'))

        d1 = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d1['server']['status'] = vm_status

        m_gs_side_effects = [(200, d1)]

        d2 = copy.deepcopy(d1)
        if vm_delete_status == 'DELETED':
            d2['server']['status'] = vm_delete_status
            m_gs_side_effects.append((200, d2))
        else:
            m_gs_side_effects.append(fakes_nova.fake_exception)

        self.patchobject(self.fc.client, 'get_servers_1234',
                         side_effect=m_gs_side_effects)
        scheduler.TaskRunner(instance.delete)()
        self.assertEqual((instance.DELETE, instance.COMPLETE), instance.state)
        self.assertEqual(2, self.fc.client.get_servers_1234.call_count)

    def _create_test_instance(self, return_server, name):
        stack_name = '%s_s' % name
        t = template_format.parse(wp_template)
        kwargs = {'KeyName': 'test',
                  'InstanceType': 'm1.large',
                  'SubnetId': '4156c7a5-e8c4-4aff-a6e1-8f3c7bc83861'}
        tmpl = template.Template(t,
                                 env=environment.Environment(kwargs))
        self.stack = parser.Stack(utils.dummy_context(), stack_name, tmpl,
                                  stack_id=str(uuid.uuid4()))
        image_id = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['ImageId'] = image_id
        resource_defns = self.stack.t.resource_definitions(self.stack)
        instance = instances.Instance('%s_name' % name,
                                      resource_defns['WebServer'], self.stack)
        metadata = instance.metadata_get()

        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)

        self._mock_get_image_id_success(image_id, 1)
        self.stub_SubnetConstraint_validate()
        self.patchobject(instance, 'neutron', return_value=FakeNeutron())

        self.patchobject(neutron.NeutronClientPlugin, '_create',
                         return_value=FakeNeutron())

        # need to resolve the template functions
        server_userdata = instance.client_plugin().build_userdata(
            metadata,
            instance.properties['UserData'],
            'ec2-user')
        self.patchobject(nova.NovaClientPlugin, 'build_userdata',
                         return_value=server_userdata)
        self.patchobject(self.fc.servers, 'create', return_value=return_server)

        scheduler.TaskRunner(instance.create)()
        self.m_f_i.assert_called_with(image_id)
        self.fc.servers.create.assert_called_once_with(
            image=1, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, instance.name),
            security_groups=None,
            userdata=server_userdata, scheduler_hints=None, meta=None,
            nics=[{'port-id': '64d913c1-bcb1-42d2-8f0a-9593dbcaf251'}],
            availability_zone=None,
            block_device_mapping=None)
        nova.NovaClientPlugin.build_userdata.assert_called_once_with(
            metadata,
            instance.properties['UserData'],
            'ec2-user')
        neutron.NeutronClientPlugin._create.assert_called_once_with()
        nova.NovaClientPlugin.client.assert_called_with()
        glance.GlanceClientPlugin.find_image_by_name_or_id.assert_called_with(
            image_id)
        return instance

    def _create_test_instance_with_nic(self, return_server, name):
        stack_name = '%s_s' % name
        t = template_format.parse(wp_template_with_nic)
        kwargs = {'KeyName': 'test',
                  'InstanceType': 'm1.large',
                  'SubnetId': '4156c7a5-e8c4-4aff-a6e1-8f3c7bc83861'}
        tmpl = template.Template(t,
                                 env=environment.Environment(kwargs))
        self.stack = parser.Stack(utils.dummy_context(), stack_name, tmpl,
                                  stack_id=str(uuid.uuid4()))
        image_id = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['ImageId'] = image_id

        resource_defns = self.stack.t.resource_definitions(self.stack)
        nic = net_interfaces.NetworkInterface('%s_nic' % name,
                                              resource_defns['nic1'],
                                              self.stack)

        instance = instances.Instance('%s_name' % name,
                                      resource_defns['WebServer'], self.stack)
        metadata = instance.metadata_get()

        self._mock_get_image_id_success(image_id, 1)
        self.stub_SubnetConstraint_validate()
        self.patchobject(nic, 'client', return_value=FakeNeutron())

        self.patchobject(neutron.NeutronClientPlugin, '_create',
                         return_value=FakeNeutron())

        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)

        # need to resolve the template functions
        server_userdata = instance.client_plugin().build_userdata(
            metadata,
            instance.properties['UserData'],
            'ec2-user')
        self.patchobject(nova.NovaClientPlugin, 'build_userdata',
                         return_value=server_userdata)
        self.patchobject(self.fc.servers, 'create', return_value=return_server)

        # create network interface
        scheduler.TaskRunner(nic.create)()
        self.stack.resources["nic1"] = nic

        scheduler.TaskRunner(instance.create)()

        self.fc.servers.create.assert_called_once_with(
            image=1, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, instance.name),
            security_groups=None,
            userdata=server_userdata, scheduler_hints=None, meta=None,
            nics=[{'port-id': '64d913c1-bcb1-42d2-8f0a-9593dbcaf251'}],
            availability_zone=None,
            block_device_mapping=None)
        self.m_f_i.assert_called_with(image_id)
        nova.NovaClientPlugin.build_userdata.assert_called_once_with(
            metadata,
            instance.properties['UserData'],
            'ec2-user')
        neutron.NeutronClientPlugin._create.assert_called_once_with()
        nova.NovaClientPlugin.client.assert_called_with()
        glance.GlanceClientPlugin.find_image_by_name_or_id.assert_called_with(
            image_id)
        return instance

    def test_instance_create_delete_with_SubnetId(self):
        self._test_instance_create_delete(vm_delete_status='DELETED')

    def test_instance_create_with_nic(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance_with_nic(
            return_server, 'in_create_wnic')

        # this makes sure the auto increment worked on instance creation
        self.assertGreater(instance.id, 0)

        expected_ip = return_server.networks['public'][0]
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicDnsName'))
