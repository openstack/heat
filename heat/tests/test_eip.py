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
import mox
from neutronclient.v2_0 import client as neutronclient
from novaclient import exceptions as nova_exceptions
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import nova
from heat.engine import parser
from heat.engine.resources import eip
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes


eip_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "EIP Test",
  "Parameters" : {},
  "Resources" : {
    "IPAddress" : {
      "Type" : "AWS::EC2::EIP",
      "Properties" : {
        "InstanceId" : { "Ref" : "WebServer" }
      }
    },
    "WebServer": {
      "Type": "AWS::EC2::Instance",
    }
  }
}
'''

eip_template_ipassoc = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "EIP Test",
  "Parameters" : {},
  "Resources" : {
    "IPAddress" : {
      "Type" : "AWS::EC2::EIP"
    },
    "IPAssoc" : {
      "Type" : "AWS::EC2::EIPAssociation",
      "Properties" : {
        "InstanceId" : { "Ref" : "WebServer" },
        "EIP" : { "Ref" : "IPAddress" }
      }
    },
    "WebServer": {
      "Type": "AWS::EC2::Instance",
    }
  }
}
'''

eip_template_ipassoc2 = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "EIP Test",
  "Parameters" : {},
  "Resources" : {
    "the_eip" : {
      "Type" : "AWS::EC2::EIP",
      "Properties" : {
        "Domain": "vpc"
      }
    },
    "IPAssoc" : {
      "Type" : "AWS::EC2::EIPAssociation",
      "Properties" : {
        "AllocationId" : 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
        "NetworkInterfaceId" : { "Ref" : "the_nic" }
      }
    },
    "the_vpc" : {
      "Type" : "AWS::EC2::VPC",
      "Properties" : {
        "CidrBlock" : "10.0.0.0/16"
      }
    },
    "the_subnet" : {
      "Type" : "AWS::EC2::Subnet",
      "Properties" : {
        "CidrBlock" : "10.0.0.0/24",
        "VpcId" : { "Ref" : "the_vpc" }
      }
    },
    "the_nic" : {
      "Type" : "AWS::EC2::NetworkInterface",
      "Properties" : {
        "PrivateIpAddress": "10.0.0.100",
        "SubnetId": { "Ref": "the_subnet" }
      }
    },
  }
}
'''

eip_template_ipassoc3 = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "EIP Test",
  "Parameters" : {},
  "Resources" : {
    "the_eip" : {
      "Type" : "AWS::EC2::EIP",
      "Properties" : {
        "Domain": "vpc"
      }
    },
    "IPAssoc" : {
      "Type" : "AWS::EC2::EIPAssociation",
      "Properties" : {
        "AllocationId" : 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
        "InstanceId" : '1fafbe59-2332-4f5f-bfa4-517b4d6c1b65'
      }
    }
  }
}
'''

ipassoc_template_validate = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "EIP Test",
  "Parameters" : {},
  "Resources" : {
    "IPAssoc" : {
      "Type" : "AWS::EC2::EIPAssociation",
      "Properties" : {
        "EIP" : '11.0.0.1',
        "InstanceId" : '1fafbe59-2332-4f5f-bfa4-517b4d6c1b65'
      }
    }
  }
}
'''


class EIPTest(HeatTestCase):
    def setUp(self):
        # force Nova, will test Neutron below
        super(EIPTest, self).setUp()
        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        self.m.StubOutWithMock(self.fc.servers, 'get')

    def create_eip(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = eip.ElasticIp(resource_name,
                             resource_defns[resource_name],
                             stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_association(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = eip.ElasticIpAssociation(resource_name,
                                        resource_defns[resource_name],
                                        stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_eip(self):
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.fc.servers.get('WebServer').AndReturn(self.fc.servers.list()[0])
        self.fc.servers.get('WebServer')

        self.m.ReplayAll()

        t = template_format.parse(eip_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_eip(t, stack, 'IPAddress')

        try:
            self.assertEqual('11.0.0.1', rsrc.FnGetRefId())
            rsrc.refid = None
            self.assertEqual('11.0.0.1', rsrc.FnGetRefId())

            self.assertEqual('1', rsrc.FnGetAtt('AllocationId'))

            self.assertRaises(exception.InvalidTemplateAttribute,
                              rsrc.FnGetAtt, 'Foo')

        finally:
            scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_eip_update(self):
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        server_old = self.fc.servers.list()[0]
        self.fc.servers.get('WebServer').AndReturn(server_old)

        server_update = self.fc.servers.list()[1]
        self.fc.servers.get('5678').MultipleTimes().AndReturn(server_update)

        self.m.ReplayAll()
        t = template_format.parse(eip_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_eip(t, stack, 'IPAddress')
        self.assertEqual('11.0.0.1', rsrc.FnGetRefId())
        # update with the new InstanceId
        props = copy.deepcopy(rsrc.properties.data)
        update_server_id = '5678'
        props['InstanceId'] = update_server_id
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('11.0.0.1', rsrc.FnGetRefId())
        # update without InstanceId
        props = copy.deepcopy(rsrc.properties.data)
        props.pop('InstanceId')
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_association_eip(self):
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.fc.servers.get('WebServer').MultipleTimes() \
            .AndReturn(self.fc.servers.list()[0])

        self.m.ReplayAll()

        t = template_format.parse(eip_template_ipassoc)
        stack = utils.parse_stack(t)

        rsrc = self.create_eip(t, stack, 'IPAddress')
        association = self.create_association(t, stack, 'IPAssoc')

        try:
            self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
            self.assertEqual((association.CREATE, association.COMPLETE),
                             association.state)

            self.assertEqual(utils.PhysName(stack.name, association.name),
                             association.FnGetRefId())
            self.assertEqual('11.0.0.1', association.properties['EIP'])
        finally:
            scheduler.TaskRunner(association.delete)()
            scheduler.TaskRunner(rsrc.delete)()

        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual((association.DELETE, association.COMPLETE),
                         association.state)

        self.m.VerifyAll()

    def test_eip_with_exception(self):
        self.m.StubOutWithMock(self.fc.floating_ips, 'create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.fc.floating_ips.create().AndRaise(fakes.fake_exception())
        self.m.ReplayAll()

        t = template_format.parse(eip_template)
        stack = utils.parse_stack(t)
        resource_name = 'IPAddress'
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = eip.ElasticIp(resource_name,
                             resource_defns[resource_name],
                             stack)

        self.assertRaises(nova_exceptions.NotFound,
                          rsrc.handle_create)
        self.m.VerifyAll()

    def test_delete_eip_with_exception(self):
        self.m.StubOutWithMock(self.fc.floating_ips, 'delete')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.fc.floating_ips.delete(mox.IsA(object)).AndRaise(
            fakes.fake_exception())
        self.fc.servers.get(mox.IsA(object)).AndReturn(False)
        self.m.ReplayAll()

        t = template_format.parse(eip_template)
        stack = utils.parse_stack(t)
        resource_name = 'IPAddress'
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = eip.ElasticIp(resource_name,
                             resource_defns[resource_name],
                             stack)
        rsrc.resource_id = 'fake_id'
        rsrc.handle_delete()
        self.m.VerifyAll()

    def test_delete_eip_successful_if_eip_associate_failed(self):
        floating_ip = mox.IsA(object)
        floating_ip.ip = '172.24.4.13'
        floating_ip.id = '9037272b-6875-42e6-82e9-4342d5925da4'

        self.m.StubOutWithMock(self.fc.floating_ips, 'create')
        self.fc.floating_ips.create().AndReturn(floating_ip)

        server = self.fc.servers.list()[0]
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.fc.servers.get('WebServer').MultipleTimes().AndReturn(server)

        self.m.StubOutWithMock(self.fc.servers, 'add_floating_ip')
        self.fc.servers.add_floating_ip(server, floating_ip.ip, None).\
            AndRaise(nova_exceptions.BadRequest(400))

        self.m.StubOutWithMock(self.fc.servers, 'remove_floating_ip')
        msg = ("ClientException: Floating ip 172.24.4.13 is not associated "
               "with instance 1234.")
        self.fc.servers.remove_floating_ip(server, floating_ip.ip).\
            AndRaise(nova_exceptions.ClientException(422, msg))
        self.m.StubOutWithMock(self.fc.floating_ips, 'delete')
        self.fc.floating_ips.delete(mox.IsA(object))

        self.m.ReplayAll()

        t = template_format.parse(eip_template)
        stack = utils.parse_stack(t)
        resource_name = 'IPAddress'
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = eip.ElasticIp(resource_name,
                             resource_defns[resource_name],
                             stack)

        self.assertIsNone(rsrc.validate())
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.create))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        # to delete the eip
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()


class AllocTest(HeatTestCase):

    def setUp(self):
        super(AllocTest, self).setUp()

        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        self.m.StubOutWithMock(parser.Stack, 'resource_by_refid')
        self.m.StubOutWithMock(neutronclient.Client,
                               'create_floatingip')
        self.m.StubOutWithMock(neutronclient.Client,
                               'show_floatingip')
        self.m.StubOutWithMock(neutronclient.Client,
                               'update_floatingip')
        self.m.StubOutWithMock(neutronclient.Client,
                               'delete_floatingip')
        self.m.StubOutWithMock(neutronclient.Client,
                               'add_gateway_router')
        self.m.StubOutWithMock(neutronclient.Client, 'list_networks')
        self.m.StubOutWithMock(neutronclient.Client, 'list_ports')
        self.m.StubOutWithMock(neutronclient.Client, 'show_network')
        self.m.StubOutWithMock(neutronclient.Client, 'list_routers')
        self.m.StubOutWithMock(neutronclient.Client,
                               'remove_gateway_router')
        self.stub_keystoneclient()

    def _setup_test_stack(self, stack_name):
        t = template_format.parse(ipassoc_template_validate)
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name,
                             template, stack_id='12233',
                             stack_user_project_id='8888')

        return template, stack

    def _validate_properties(self, stack, template, expected):
        resource_defns = template.resource_definitions(stack)
        rsrc = eip.ElasticIpAssociation('validate_eip_ass',
                                        resource_defns['IPAssoc'],
                                        stack)

        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn(expected, six.text_type(exc))

    def mock_show_network(self):
        vpc_name = utils.PhysName('test_stack', 'the_vpc')
        neutronclient.Client.show_network(
            '22c26451-cf27-4d48-9031-51f5e397b84e'
        ).AndReturn({"network": {
            "status": "BUILD",
            "subnets": [],
            "name": vpc_name,
            "admin_state_up": False,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "22c26451-cf27-4d48-9031-51f5e397b84e"
        }})

    def create_eip(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = eip.ElasticIp(resource_name,
                             resource_defns[resource_name],
                             stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_association(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = eip.ElasticIpAssociation(resource_name,
                                        resource_defns[resource_name],
                                        stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def mock_update_floatingip(self, port='the_nic'):
        neutronclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'floatingip': {'port_id': port}}).AndReturn(None)

    def mock_create_gateway_attachment(self):
        neutronclient.Client.add_gateway_router(
            'bbbb', {'network_id': 'eeee'}).AndReturn(None)

    def mock_create_floatingip(self):
        neutronclient.Client.list_networks(
            **{'router:external': True}).AndReturn({'networks': [{
                'status': 'ACTIVE',
                'subnets': [],
                'name': 'nova',
                'router:external': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'admin_state_up': True,
                'shared': True,
                'id': 'eeee'
            }]})

        neutronclient.Client.create_floatingip({
            'floatingip': {'floating_network_id': u'eeee'}
        }).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
            "floating_ip_address": "192.168.9.3"
        }})

    def mock_show_floatingip(self, refid):
        neutronclient.Client.show_floatingip(
            refid,
        ).AndReturn({'floatingip': {
            'router_id': None,
            'tenant_id': 'e936e6cd3e0b48dcb9ff853a8f253257',
            'floating_network_id': 'eeee',
            'fixed_ip_address': None,
            'floating_ip_address': '172.24.4.227',
            'port_id': None,
            'id': 'ffff'
        }})

    def mock_delete_floatingip(self):
        id = 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        neutronclient.Client.delete_floatingip(id).AndReturn(None)

    def mock_list_ports(self, id='the_nic'):
        neutronclient.Client.list_ports(id=id).AndReturn(
            {"ports": [{
                "status": "DOWN",
                "binding:host_id": "null",
                "name": "wp-NIC-yu7fc7l4g5p6",
                "admin_state_up": True,
                "network_id": "22c26451-cf27-4d48-9031-51f5e397b84e",
                "tenant_id": "ecf538ec1729478fa1f97f1bf4fdcf7b",
                "binding:vif_type": "ovs",
                "device_owner": "",
                "binding:capabilities": {"port_filter": True},
                "mac_address": "fa:16:3e:62:2d:4f",
                "fixed_ips": [{"subnet_id": "mysubnetid-70ec",
                               "ip_address": "192.168.9.2"}],
                "id": "a000228d-b40b-4124-8394-a4082ae1b76b",
                "security_groups": ["5c6f529d-3186-4c36-84c0-af28b8daac7b"],
                "device_id": ""
            }]})

    def mock_list_instance_ports(self, refid):
        neutronclient.Client.list_ports(device_id=refid).AndReturn(
            {"ports": [{
                "status": "DOWN",
                "binding:host_id": "null",
                "name": "wp-NIC-yu7fc7l4g5p6",
                "admin_state_up": True,
                "network_id": "22c26451-cf27-4d48-9031-51f5e397b84e",
                "tenant_id": "ecf538ec1729478fa1f97f1bf4fdcf7b",
                "binding:vif_type": "ovs",
                "device_owner": "",
                "binding:capabilities": {"port_filter": True},
                "mac_address": "fa:16:3e:62:2d:4f",
                "fixed_ips": [{"subnet_id": "mysubnetid-70ec",
                               "ip_address": "192.168.9.2"}],
                "id": "a000228d-b40b-4124-8394-a4082ae1b76c",
                "security_groups": ["5c6f529d-3186-4c36-84c0-af28b8daac7b"],
                "device_id": refid
            }]})

    def mock_router_for_vpc(self):
        vpc_name = utils.PhysName('test_stack', 'the_vpc')
        neutronclient.Client.list_routers(name=vpc_name).AndReturn({
            "routers": [{
                "status": "ACTIVE",
                "external_gateway_info": {
                    "network_id": "zzzz",
                    "enable_snat": True},
                "name": vpc_name,
                "admin_state_up": True,
                "tenant_id": "3e21026f2dc94372b105808c0e721661",
                "routes": [],
                "id": "bbbb"
            }]
        })

    def mock_no_router_for_vpc(self):
        vpc_name = utils.PhysName('test_stack', 'the_vpc')
        neutronclient.Client.list_routers(name=vpc_name).AndReturn({
            "routers": []
        })

    def test_neutron_eip(self):
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.fc.servers.get('WebServer').AndReturn(self.fc.servers.list()[0])
        self.fc.servers.get('WebServer')

        self.m.ReplayAll()

        t = template_format.parse(eip_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_eip(t, stack, 'IPAddress')

        try:
            self.assertEqual('11.0.0.1', rsrc.FnGetRefId())
            rsrc.refid = None
            self.assertEqual('11.0.0.1', rsrc.FnGetRefId())

            self.assertEqual('1', rsrc.FnGetAtt('AllocationId'))

            self.assertRaises(exception.InvalidTemplateAttribute,
                              rsrc.FnGetAtt, 'Foo')

        finally:
            scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_association_allocationid(self):
        self.mock_create_gateway_attachment()
        self.mock_show_network()
        self.mock_router_for_vpc()

        self.mock_create_floatingip()
        self.mock_list_ports()

        self.mock_show_floatingip('fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        self.mock_update_floatingip()

        self.mock_update_floatingip(port=None)
        self.mock_delete_floatingip()

        self.m.ReplayAll()

        t = template_format.parse(eip_template_ipassoc2)
        stack = utils.parse_stack(t)

        rsrc = self.create_eip(t, stack, 'the_eip')
        association = self.create_association(t, stack, 'IPAssoc')

        scheduler.TaskRunner(association.delete)()
        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_association_allocationid_with_instance(self):
        self.mock_show_network()

        self.mock_create_floatingip()
        self.mock_list_instance_ports('1fafbe59-2332-4f5f-bfa4-517b4d6c1b65')

        self.mock_no_router_for_vpc()
        self.mock_update_floatingip(
            port='a000228d-b40b-4124-8394-a4082ae1b76c')

        self.mock_update_floatingip(port=None)
        self.mock_delete_floatingip()

        self.m.ReplayAll()

        t = template_format.parse(eip_template_ipassoc3)
        stack = utils.parse_stack(t)

        rsrc = self.create_eip(t, stack, 'the_eip')
        association = self.create_association(t, stack, 'IPAssoc')

        scheduler.TaskRunner(association.delete)()
        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_validate_properties_EIP_and_AllocationId(self):
        template, stack = self._setup_test_stack(
            stack_name='validate_EIP_AllocationId')

        properties = template.t['Resources']['IPAssoc']['Properties']
        # test with EIP and AllocationId
        properties['AllocationId'] = 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        expected = ("Either 'EIP' or 'AllocationId' must be provided.")
        self._validate_properties(stack, template, expected)

        # test without EIP and AllocationId
        properties.pop('AllocationId')
        properties.pop('EIP')
        self._validate_properties(stack, template, expected)

    def test_validate_EIP_and_InstanceId(self):
        template, stack = self._setup_test_stack(
            stack_name='validate_EIP_InstanceId')
        properties = template.t['Resources']['IPAssoc']['Properties']
        # test with EIP and no InstanceId
        properties.pop('InstanceId')
        expected = ("Must specify 'InstanceId' if you specify 'EIP'.")
        self._validate_properties(stack, template, expected)

    def test_validate_without_NetworkInterfaceId_and_InstanceId(self):
        template, stack = self._setup_test_stack(
            stack_name='validate_EIP_InstanceId')

        properties = template.t['Resources']['IPAssoc']['Properties']
        # test without NetworkInterfaceId and InstanceId
        properties.pop('InstanceId')
        properties.pop('EIP')
        allocation_id = '1fafbe59-2332-4f5f-bfa4-517b4d6c1b65'
        properties['AllocationId'] = allocation_id
        expected = ("Must specify at least one of 'InstanceId' "
                    "or 'NetworkInterfaceId'.")
        self._validate_properties(stack, template, expected)

    def test_delete_association_successful_if_create_failed(self):
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        server = self.fc.servers.list()[0]
        self.fc.servers.get('WebServer').MultipleTimes() \
            .AndReturn(server)
        self.m.StubOutWithMock(self.fc.servers, 'add_floating_ip')
        self.fc.servers.add_floating_ip(server, '11.0.0.1').AndRaise(
            fakes.fake_exception(400))
        self.m.ReplayAll()

        t = template_format.parse(eip_template_ipassoc)
        stack = utils.parse_stack(t)

        self.create_eip(t, stack, 'IPAddress')
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = eip.ElasticIpAssociation('IPAssoc',
                                        resource_defns['IPAssoc'],
                                        stack)
        self.assertIsNone(rsrc.validate())
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.create))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_update_association_with_InstanceId(self):
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        server = self.fc.servers.list()[0]
        self.fc.servers.get('WebServer').MultipleTimes() \
            .AndReturn(server)
        server_update = self.fc.servers.list()[1]
        self.fc.servers.get('5678').AndReturn(server_update)

        self.m.ReplayAll()

        t = template_format.parse(eip_template_ipassoc)
        stack = utils.parse_stack(t)
        self.create_eip(t, stack, 'IPAddress')
        ass = self.create_association(t, stack, 'IPAssoc')
        self.assertEqual('11.0.0.1', ass.properties['EIP'])

        # update with the new InstanceId
        props = copy.deepcopy(ass.properties.data)
        update_server_id = '5678'
        props['InstanceId'] = update_server_id
        update_snippet = rsrc_defn.ResourceDefinition(ass.name, ass.type(),
                                                      stack.t.parse(stack,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)

        self.m.VerifyAll()

    def test_update_association_with_EIP(self):
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        server = self.fc.servers.list()[0]
        self.fc.servers.get('WebServer').MultipleTimes() \
            .AndReturn(server)

        self.m.ReplayAll()

        t = template_format.parse(eip_template_ipassoc)
        stack = utils.parse_stack(t)
        self.create_eip(t, stack, 'IPAddress')
        ass = self.create_association(t, stack, 'IPAssoc')

        # update with the new EIP
        props = copy.deepcopy(ass.properties.data)
        update_eip = '11.0.0.2'
        props['EIP'] = update_eip
        update_snippet = rsrc_defn.ResourceDefinition(ass.name, ass.type(),
                                                      stack.t.parse(stack,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)

        self.m.VerifyAll()

    def test_update_association_with_AllocationId_or_EIP(self):
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        server = self.fc.servers.list()[0]
        self.fc.servers.get('WebServer').MultipleTimes()\
            .AndReturn(server)

        self.mock_list_instance_ports('WebServer')
        self.mock_show_network()
        self.mock_no_router_for_vpc()
        self.mock_update_floatingip(
            port='a000228d-b40b-4124-8394-a4082ae1b76c')

        self.mock_update_floatingip(port=None)
        self.m.ReplayAll()

        t = template_format.parse(eip_template_ipassoc)
        stack = utils.parse_stack(t)
        self.create_eip(t, stack, 'IPAddress')
        ass = self.create_association(t, stack, 'IPAssoc')
        self.assertEqual('11.0.0.1', ass.properties['EIP'])

        # change EIP to AllocationId
        props = copy.deepcopy(ass.properties.data)
        update_allocationId = 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        props['AllocationId'] = update_allocationId
        props.pop('EIP')
        update_snippet = rsrc_defn.ResourceDefinition(ass.name, ass.type(),
                                                      stack.t.parse(stack,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)

        # change AllocationId to EIP
        props = copy.deepcopy(ass.properties.data)
        update_eip = '11.0.0.2'
        props['EIP'] = update_eip
        props.pop('AllocationId')
        update_snippet = rsrc_defn.ResourceDefinition(ass.name, ass.type(),
                                                      stack.t.parse(stack,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)

        self.m.VerifyAll()

    def test_update_association_with_NetworkInterfaceId_or_InstanceId(self):
        self.mock_create_floatingip()
        self.mock_list_ports()
        self.mock_show_network()
        self.mock_no_router_for_vpc()
        self.mock_update_floatingip()

        self.mock_list_ports(id='a000228d-b40b-4124-8394-a4082ae1b76b')
        self.mock_show_network()
        self.mock_no_router_for_vpc()
        self.mock_update_floatingip(
            port='a000228d-b40b-4124-8394-a4082ae1b76b')

        self.mock_list_instance_ports('5678')
        self.mock_show_network()
        self.mock_no_router_for_vpc()
        self.mock_update_floatingip(
            port='a000228d-b40b-4124-8394-a4082ae1b76c')

        self.m.ReplayAll()

        t = template_format.parse(eip_template_ipassoc2)
        stack = utils.parse_stack(t)
        self.create_eip(t, stack, 'the_eip')
        ass = self.create_association(t, stack, 'IPAssoc')

        # update with the new NetworkInterfaceId
        props = copy.deepcopy(ass.properties.data)
        update_networkInterfaceId = 'a000228d-b40b-4124-8394-a4082ae1b76b'
        props['NetworkInterfaceId'] = update_networkInterfaceId

        update_snippet = rsrc_defn.ResourceDefinition(ass.name, ass.type(),
                                                      stack.t.parse(stack,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)

        # update with the InstanceId
        props = copy.deepcopy(ass.properties.data)
        instance_id = '5678'
        props.pop('NetworkInterfaceId')
        props['InstanceId'] = instance_id

        update_snippet = rsrc_defn.ResourceDefinition(ass.name, ass.type(),
                                                      stack.t.parse(stack,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)

        self.m.VerifyAll()
