
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

import mox
from testtools import skipIf

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine import parser
from heat.engine import resource
from heat.engine.resources import eip
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import fakes as fakec
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


def force_networking(mode):
    if mode == 'nova':
        force_networking.client = clients.neutronclient
        clients.neutronclient = None
    if mode == 'neutron':
        clients.neutronclient = force_networking.client
force_networking.client = None


class EIPTest(HeatTestCase):
    def setUp(self):
        # force Nova, will test Neutron below
        force_networking('nova')
        super(EIPTest, self).setUp()
        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(eip.ElasticIp, 'nova')
        self.m.StubOutWithMock(eip.ElasticIpAssociation, 'nova')
        self.m.StubOutWithMock(self.fc.servers, 'get')
        utils.setup_dummy_db()

    def tearDown(self):
        super(EIPTest, self).tearDown()
        force_networking('neutron')

    def create_eip(self, t, stack, resource_name):
        rsrc = eip.ElasticIp(resource_name,
                             t['Resources'][resource_name],
                             stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_association(self, t, stack, resource_name):
        rsrc = eip.ElasticIpAssociation(resource_name,
                                        t['Resources'][resource_name],
                                        stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_eip(self):
        eip.ElasticIp.nova().MultipleTimes().AndReturn(self.fc)
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

            self.assertRaises(resource.UpdateReplace,
                              rsrc.handle_update, {}, {}, {})

            self.assertRaises(exception.InvalidTemplateAttribute,
                              rsrc.FnGetAtt, 'Foo')

        finally:
            scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_association_eip(self):
        eip.ElasticIp.nova().MultipleTimes().AndReturn(self.fc)
        eip.ElasticIpAssociation.nova().MultipleTimes().AndReturn(self.fc)
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
        eip.ElasticIp.nova().MultipleTimes().AndReturn(self.fc)
        self.fc.floating_ips.create().AndRaise(
            clients.novaclient.exceptions.NotFound('fake_falure'))
        self.m.ReplayAll()

        t = template_format.parse(eip_template)
        stack = utils.parse_stack(t)
        resource_name = 'IPAddress'
        rsrc = eip.ElasticIp(resource_name,
                             t['Resources'][resource_name],
                             stack)

        self.assertRaises(clients.novaclient.exceptions.NotFound,
                          rsrc.handle_create)
        self.m.VerifyAll()

    def test_delete_eip_with_exception(self):
        self.m.StubOutWithMock(self.fc.floating_ips, 'delete')
        eip.ElasticIp.nova().MultipleTimes().AndReturn(self.fc)
        self.fc.floating_ips.delete(mox.IsA(object)).AndRaise(
            clients.novaclient.exceptions.NotFound('fake_falure'))
        self.fc.servers.get(mox.IsA(object)).AndReturn(False)
        self.m.ReplayAll()

        t = template_format.parse(eip_template)
        stack = utils.parse_stack(t)
        resource_name = 'IPAddress'
        rsrc = eip.ElasticIp(resource_name,
                             t['Resources'][resource_name],
                             stack)
        rsrc.resource_id = 'fake_id'
        rsrc.handle_delete()
        self.m.VerifyAll()


class AllocTest(HeatTestCase):

    @skipIf(clients.neutronclient is None, 'neutronclient unavailable')
    def setUp(self):
        super(AllocTest, self).setUp()

        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(eip.ElasticIp, 'nova')
        self.m.StubOutWithMock(eip.ElasticIpAssociation, 'nova')
        self.m.StubOutWithMock(self.fc.servers, 'get')

        self.m.StubOutWithMock(parser.Stack, 'resource_by_refid')
        self.m.StubOutWithMock(clients.neutronclient.Client,
                               'create_floatingip')
        self.m.StubOutWithMock(clients.neutronclient.Client,
                               'show_floatingip')
        self.m.StubOutWithMock(clients.neutronclient.Client,
                               'update_floatingip')
        self.m.StubOutWithMock(clients.neutronclient.Client,
                               'delete_floatingip')
        self.m.StubOutWithMock(clients.neutronclient.Client,
                               'add_gateway_router')
        self.m.StubOutWithMock(clients.neutronclient.Client, 'list_networks')
        self.m.StubOutWithMock(clients.neutronclient.Client, 'list_ports')
        self.m.StubOutWithMock(clients.neutronclient.Client, 'list_subnets')
        self.m.StubOutWithMock(clients.neutronclient.Client, 'show_network')
        self.m.StubOutWithMock(clients.neutronclient.Client, 'list_routers')
        self.m.StubOutWithMock(clients.neutronclient.Client,
                               'remove_gateway_router')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')

        utils.setup_dummy_db()

    def mock_show_network(self):
        vpc_name = utils.PhysName('test_stack', 'the_vpc')
        clients.neutronclient.Client.show_network(
            'aaaa-netid'
        ).AndReturn({"network": {
            "status": "BUILD",
            "subnets": [],
            "name": vpc_name,
            "admin_state_up": False,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "aaaa-netid"
        }})

    def create_eip(self, t, stack, resource_name):
        rsrc = eip.ElasticIp(resource_name,
                             t['Resources'][resource_name],
                             stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_association(self, t, stack, resource_name):
        rsrc = eip.ElasticIpAssociation(resource_name,
                                        t['Resources'][resource_name],
                                        stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def mock_update_floatingip(self, port='the_nic'):
        clients.neutronclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'floatingip': {'port_id': port}}).AndReturn(None)

    def mock_create_gateway_attachment(self):
        clients.neutronclient.Client.add_gateway_router(
            'bbbb', {'network_id': 'eeee'}).AndReturn(None)

    def mock_create_floatingip(self):
        clients.neutronclient.Client.list_networks(
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

        clients.neutronclient.Client.create_floatingip({
            'floatingip': {'floating_network_id': u'eeee'}
        }).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
            "floating_ip_address": "192.168.9.3"
        }})

    def mock_show_floatingip(self, refid):
        clients.neutronclient.Client.show_floatingip(
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
        clients.neutronclient.Client.delete_floatingip(id).AndReturn(None)

    def mock_list_ports(self):
        clients.neutronclient.Client.list_ports(id='the_nic').AndReturn(
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
        clients.neutronclient.Client.list_ports(device_id=refid).AndReturn(
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

    def mock_list_subnets(self):
        clients.neutronclient.Client.list_subnets(
            id='mysubnetid-70ec').AndReturn(
                {'subnets': [{
                    u'name': u'wp-Subnet-pyjm7bvoi4xw',
                    u'enable_dhcp': True,
                    u'network_id': u'aaaa-netid',
                    u'tenant_id': u'ecf538ec1729478fa1f97f1bf4fdcf7b',
                    u'dns_nameservers': [],
                    u'allocation_pools': [{u'start': u'192.168.9.2',
                                           u'end': u'192.168.9.254'}],
                    u'host_routes': [],
                    u'ip_version': 4,
                    u'gateway_ip': u'192.168.9.1',
                    u'cidr': u'192.168.9.0/24',
                    u'id': u'2c339ccd-734a-4acc-9f64-6f0dfe427e2d'
                }]})

    def mock_router_for_vpc(self):
        vpc_name = utils.PhysName('test_stack', 'the_vpc')
        clients.neutronclient.Client.list_routers(name=vpc_name).AndReturn({
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
        clients.neutronclient.Client.list_routers(name=vpc_name).AndReturn({
            "routers": []
        })

    def mock_keystone(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakec.FakeKeystoneClient())

    def test_neutron_eip(self):
        eip.ElasticIp.nova().MultipleTimes().AndReturn(self.fc)
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

            self.assertRaises(resource.UpdateReplace,
                              rsrc.handle_update, {}, {}, {})

            self.assertRaises(exception.InvalidTemplateAttribute,
                              rsrc.FnGetAtt, 'Foo')

        finally:
            scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_association_allocationid(self):
        self.mock_keystone()
        self.mock_create_gateway_attachment()
        self.mock_show_network()
        self.mock_router_for_vpc()

        self.mock_create_floatingip()
        self.mock_list_ports()
        self.mock_list_subnets()

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
        self.mock_keystone()
        self.mock_show_network()

        self.mock_create_floatingip()
        self.mock_list_instance_ports('1fafbe59-2332-4f5f-bfa4-517b4d6c1b65')
        self.mock_list_subnets()

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
