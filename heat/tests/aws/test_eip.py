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
from neutronclient.common import exceptions as q_exceptions
from neutronclient.v2_0 import client as neutronclient
import six

from heat.common import exception
from heat.common import short_id
from heat.common import template_format
from heat.engine.clients.os import nova
from heat.engine import node_data
from heat.engine import resource
from heat.engine.resources.aws.ec2 import eip
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import stk_defn
from heat.engine import template as tmpl
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


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
    "eip" : {
      "Type" : "AWS::EC2::EIP",
      "Properties" : {
        "Domain": "vpc"
      }
    },
    "IPAssoc" : {
      "Type" : "AWS::EC2::EIPAssociation",
      "Properties" : {
        "EIP" : {'Ref': 'eip'},
        "InstanceId" : '1fafbe59-2332-4f5f-bfa4-517b4d6c1b65'
      }
    }
  }
}
'''


class EIPTest(common.HeatTestCase):
    def setUp(self):
        # force Nova, will test Neutron below
        super(EIPTest, self).setUp()
        self.fc = fakes_nova.FakeClient()
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        self.mock_list_net = self.patchobject(neutronclient.Client,
                                              'list_networks')
        self.mock_create_fip = self.patchobject(neutronclient.Client,
                                                'create_floatingip')
        self.mock_show_fip = self.patchobject(neutronclient.Client,
                                              'show_floatingip')
        self.patchobject(neutronclient.Client, 'update_floatingip')
        self.patchobject(neutronclient.Client, 'delete_floatingip')
        self.mock_list_fips = self.patchobject(neutronclient.Client,
                                               'list_floatingips')

    def mock_interface(self, port, ip):
        class MockIface(object):
            def __init__(self, port_id, fixed_ip):
                self.port_id = port_id
                self.fixed_ips = [{'ip_address': fixed_ip}]

        return MockIface(port, ip)

    def mock_list_floatingips(self):
        self.mock_list_fips.return_value = {
            'floatingips': [{'id':
                             "fc68ea2c-b60b-4b4f-bd82-94ec81110766"}]}

    def mock_create_floatingip(self):
        self.mock_list_net.return_value = {'networks': [{
            'status': 'ACTIVE',
            'subnets': [],
            'name': 'nova',
            'router:external': True,
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'admin_state_up': True,
            'shared': True,
            'id': 'eeee'
        }]}

        self.mock_create_fip.return_value = {'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
            "floating_ip_address": "11.0.0.1"
        }}

    def mock_show_floatingip(self):
        self.mock_show_fip.return_value = {'floatingip': {
            'router_id': None,
            'tenant_id': 'e936e6cd3e0b48dcb9ff853a8f253257',
            'floating_network_id': 'eeee',
            'fixed_ip_address': None,
            'floating_ip_address': '11.0.0.1',
            'port_id': None,
            'id': 'ffff'
        }}

    def create_eip(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = eip.ElasticIp(resource_name,
                             resource_defns[resource_name],
                             stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        stk_defn.update_resource_data(stack.defn, resource_name,
                                      rsrc.node_data())
        return rsrc

    def create_association(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = eip.ElasticIpAssociation(resource_name,
                                        resource_defns[resource_name],
                                        stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        stk_defn.update_resource_data(stack.defn, resource_name,
                                      rsrc.node_data())
        return rsrc

    def test_eip(self):
        mock_server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get',
                         return_value=mock_server)
        self.mock_create_floatingip()
        iface = self.mock_interface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                    '1.2.3.4')
        self.patchobject(mock_server, 'interface_list', return_value=[iface])

        t = template_format.parse(eip_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_eip(t, stack, 'IPAddress')

        try:
            self.assertEqual('11.0.0.1', rsrc.FnGetRefId())
            rsrc.refid = None
            self.assertEqual('11.0.0.1', rsrc.FnGetRefId())

            self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                             rsrc.FnGetAtt('AllocationId'))

            self.assertRaises(exception.InvalidTemplateAttribute,
                              rsrc.FnGetAtt, 'Foo')

        finally:
            scheduler.TaskRunner(rsrc.destroy)()

    def test_eip_update(self):
        server_old = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get',
                         return_value=server_old)
        iface = self.mock_interface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                    '1.2.3.4')
        self.patchobject(server_old, 'interface_list', return_value=[iface])
        self.mock_create_floatingip()
        t = template_format.parse(eip_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_eip(t, stack, 'IPAddress')
        self.assertEqual('11.0.0.1', rsrc.FnGetRefId())
        # update with the new InstanceId
        server_update = self.fc.servers.list()[1]
        self.patchobject(self.fc.servers, 'get',
                         return_value=server_update)
        self.patchobject(server_update, 'interface_list', return_value=[iface])
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

    def test_association_eip(self):
        mock_server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get',
                         return_value=mock_server)
        iface = self.mock_interface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                    '1.2.3.4')
        self.patchobject(mock_server, 'interface_list', return_value=[iface])
        self.mock_create_floatingip()
        self.mock_show_floatingip()
        self.mock_list_floatingips()
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

    def test_eip_with_exception(self):
        self.mock_list_net.return_value = {'networks': [{
            'status': 'ACTIVE',
            'subnets': [],
            'name': 'nova',
            'router:external': True,
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'admin_state_up': True,
            'shared': True,
            'id': 'eeee'
        }]}
        self.patchobject(neutronclient.Client, 'create_floatingip',
                         side_effect=neutronclient.exceptions.NotFound)
        t = template_format.parse(eip_template)
        stack = utils.parse_stack(t)
        resource_name = 'IPAddress'
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = eip.ElasticIp(resource_name,
                             resource_defns[resource_name],
                             stack)

        self.assertRaises(neutronclient.exceptions.NotFound,
                          rsrc.handle_create)

    @mock.patch.object(eip.ElasticIp, '_ipaddress')
    def test_FnGetRefId_resource_name(self, mock_ipaddr):
        t = template_format.parse(ipassoc_template_validate)
        stack = utils.parse_stack(t)
        rsrc = stack['eip']
        mock_ipaddr.return_value = None
        self.assertEqual('eip', rsrc.FnGetRefId())

    @mock.patch.object(eip.ElasticIp, '_ipaddress')
    def test_FnGetRefId_resource_ip(self, mock_ipaddr):
        t = template_format.parse(ipassoc_template_validate)
        stack = utils.parse_stack(t)
        rsrc = stack['eip']
        mock_ipaddr.return_value = 'x.x.x.x'
        self.assertEqual('x.x.x.x', rsrc.FnGetRefId())

    def test_FnGetRefId_convergence_cache_data(self):
        t = template_format.parse(ipassoc_template_validate)
        template = tmpl.Template(t)
        stack = parser.Stack(utils.dummy_context(), 'test', template,
                             cache_data={
                                 'eip': node_data.NodeData.from_dict({
                                     'uuid': mock.ANY,
                                     'id': mock.ANY,
                                     'action': 'CREATE',
                                     'status': 'COMPLETE',
                                     'reference_id': '1.1.1.1'})})

        rsrc = stack.defn['eip']
        self.assertEqual('1.1.1.1', rsrc.FnGetRefId())


class AllocTest(common.HeatTestCase):

    def setUp(self):
        super(AllocTest, self).setUp()
        self.fc = fakes_nova.FakeClient()
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        self.mock_list_net = self.patchobject(neutronclient.Client,
                                              'list_networks')
        self.mock_create_fip = self.patchobject(neutronclient.Client,
                                                'create_floatingip')
        self.mock_show_fip = self.patchobject(neutronclient.Client,
                                              'show_floatingip')
        self.patchobject(neutronclient.Client, 'update_floatingip')
        self.patchobject(neutronclient.Client, 'delete_floatingip')
        self.mock_list_fips = self.patchobject(neutronclient.Client,
                                               'list_floatingips')
        self.patchobject(neutronclient.Client, 'add_gateway_router')
        self.mock_list_ports = self.patchobject(neutronclient.Client,
                                                'list_ports')
        self.mock_show_net = self.patchobject(neutronclient.Client,
                                              'show_network')
        self.mock_list_routers = self.patchobject(neutronclient.Client,
                                                  'list_routers')
        self.patchobject(neutronclient.Client,
                         'remove_gateway_router')

    def mock_interface(self, port, ip):
        class MockIface(object):
            def __init__(self, port_id, fixed_ip):
                self.port_id = port_id
                self.fixed_ips = [{'ip_address': fixed_ip}]

        return MockIface(port, ip)

    def _setup_test_stack_validate(self, stack_name):
        t = template_format.parse(ipassoc_template_validate)
        template = tmpl.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name,
                             template, stack_id='12233',
                             stack_user_project_id='8888')
        stack.validate()

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
        self.mock_show_net.return_value = {"network": {
            "status": "BUILD",
            "subnets": [],
            "name": vpc_name,
            "admin_state_up": False,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "22c26451-cf27-4d48-9031-51f5e397b84e"
        }}

    def create_eip(self, t, stack, resource_name):
        rsrc = eip.ElasticIp(resource_name,
                             stack.defn.resource_definition(resource_name),
                             stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        stk_defn.update_resource_data(stack.defn, resource_name,
                                      rsrc.node_data())
        return rsrc

    def create_association(self, t, stack, resource_name):
        resource_defn = stack.defn.resource_definition(resource_name)
        rsrc = eip.ElasticIpAssociation(resource_name,
                                        resource_defn,
                                        stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        stk_defn.update_resource_data(stack.defn, resource_name,
                                      rsrc.node_data())
        return rsrc

    def mock_create_floatingip(self):
        self.mock_list_net.return_value = {'networks': [{
            'status': 'ACTIVE',
            'subnets': [],
            'name': 'nova',
            'router:external': True,
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'admin_state_up': True,
            'shared': True,
            'id': 'eeee'
        }]}

        self.mock_create_fip.return_value = {'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
            "floating_ip_address": "11.0.0.1"
        }}

    def mock_list_floatingips(self):
        self.mock_list_fips.return_value = {
            'floatingips': [{'id':
                             "fc68ea2c-b60b-4b4f-bd82-94ec81110766"}]}

    def mock_show_floatingip(self):
        self.mock_show_fip.return_value = {'floatingip': {
            'router_id': None,
            'tenant_id': 'e936e6cd3e0b48dcb9ff853a8f253257',
            'floating_network_id': 'eeee',
            'fixed_ip_address': None,
            'floating_ip_address': '11.0.0.1',
            'port_id': None,
            'id': 'ffff'
        }}

    def mock_list_ports(self):
        self.mock_list_ports.return_value = {"ports": [{
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
        }]}

    def mock_list_instance_ports(self):
        self.mock_list_ports.return_value = {"ports": [{
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
            "device_id": ""
        }]}

    def mock_router_for_vpc(self):
        vpc_name = utils.PhysName('test_stack', 'the_vpc')
        self.mock_list_routers.return_value = {
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
        }

    def mock_no_router_for_vpc(self):
        self.mock_list_routers.return_value = {
            "routers": []
        }

    def test_association_allocationid(self):
        self.mock_create_floatingip()
        self.mock_router_for_vpc()
        self.mock_show_network()
        self.mock_list_ports()
        self.mock_show_floatingip()
        t = template_format.parse(eip_template_ipassoc2)
        stack = utils.parse_stack(t)

        rsrc = self.create_eip(t, stack, 'the_eip')
        association = self.create_association(t, stack, 'IPAssoc')

        scheduler.TaskRunner(association.delete)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((association.DELETE, association.COMPLETE),
                         association.state)
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

    def test_association_allocationid_with_instance(self):
        server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get', return_value=server)
        self.mock_show_network()

        self.mock_create_floatingip()
        self.mock_list_instance_ports()

        self.mock_no_router_for_vpc()

        t = template_format.parse(eip_template_ipassoc3)
        stack = utils.parse_stack(t)

        rsrc = self.create_eip(t, stack, 'the_eip')
        association = self.create_association(t, stack, 'IPAssoc')

        scheduler.TaskRunner(association.delete)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((association.DELETE, association.COMPLETE),
                         association.state)
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

    def test_validate_properties_EIP_and_AllocationId(self):
        server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get', return_value=server)
        template, stack = self._setup_test_stack_validate(
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
        server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get', return_value=server)
        template, stack = self._setup_test_stack_validate(
            stack_name='validate_EIP_InstanceId')
        properties = template.t['Resources']['IPAssoc']['Properties']
        # test with EIP and no InstanceId
        properties.pop('InstanceId')
        expected = ("Must specify 'InstanceId' if you specify 'EIP'.")
        self._validate_properties(stack, template, expected)

    def test_validate_without_NetworkInterfaceId_and_InstanceId(self):
        server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get', return_value=server)
        template, stack = self._setup_test_stack_validate(
            stack_name='validate_EIP_InstanceId')

        properties = template.t['Resources']['IPAssoc']['Properties']
        # test without NetworkInterfaceId and InstanceId
        properties.pop('InstanceId')
        properties.pop('EIP')
        allocation_id = '1fafbe59-2332-4f5f-bfa4-517b4d6c1b65'
        properties['AllocationId'] = allocation_id
        resource_defns = template.resource_definitions(stack)
        rsrc = eip.ElasticIpAssociation('validate_eip_ass',
                                        resource_defns['IPAssoc'],
                                        stack)
        exc = self.assertRaises(exception.PropertyUnspecifiedError,
                                rsrc.validate)
        self.assertIn('At least one of the following properties '
                      'must be specified: InstanceId, NetworkInterfaceId',
                      six.text_type(exc))

    def test_delete_association_successful_if_create_failed(self):
        server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get', return_value=server)
        self.mock_create_floatingip()
        self.mock_show_floatingip()
        self.patchobject(server, 'interface_list',
                         side_effect=[q_exceptions.NotFound('Not FOund')])
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

    def test_update_association_with_InstanceId(self):
        server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get', return_value=server)
        iface = self.mock_interface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                    '1.2.3.4')
        self.patchobject(server, 'interface_list', return_value=[iface])
        self.mock_create_floatingip()
        self.mock_list_floatingips()
        t = template_format.parse(eip_template_ipassoc)
        stack = utils.parse_stack(t)
        self.create_eip(t, stack, 'IPAddress')
        ass = self.create_association(t, stack, 'IPAssoc')
        self.assertEqual('11.0.0.1', ass.properties['EIP'])

        server_update = self.fc.servers.list()[1]
        self.patchobject(self.fc.servers, 'get', return_value=server_update)
        self.patchobject(server_update, 'interface_list', return_value=[iface])
        # update with the new InstanceId
        props = copy.deepcopy(ass.properties.data)
        update_server_id = '5678'
        props['InstanceId'] = update_server_id
        update_snippet = rsrc_defn.ResourceDefinition(ass.name, ass.type(),
                                                      stack.t.parse(stack.defn,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)

    def test_update_association_with_EIP(self):
        server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get', return_value=server)
        iface = self.mock_interface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                    '1.2.3.4')
        self.patchobject(server, 'interface_list', return_value=[iface])
        self.mock_create_floatingip()
        self.mock_list_floatingips()
        t = template_format.parse(eip_template_ipassoc)
        stack = utils.parse_stack(t)
        self.create_eip(t, stack, 'IPAddress')
        ass = self.create_association(t, stack, 'IPAssoc')

        # update with the new EIP
        props = copy.deepcopy(ass.properties.data)
        update_eip = '11.0.0.2'
        props['EIP'] = update_eip
        update_snippet = rsrc_defn.ResourceDefinition(ass.name, ass.type(),
                                                      stack.t.parse(stack.defn,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)

    def test_update_association_with_AllocationId_or_EIP(self):
        server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get', return_value=server)
        iface = self.mock_interface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                    '1.2.3.4')
        self.patchobject(server, 'interface_list', return_value=[iface])
        self.mock_create_floatingip()
        self.mock_list_floatingips()
        self.mock_list_instance_ports()
        self.mock_show_network()
        self.mock_no_router_for_vpc()

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
                                                      stack.t.parse(stack.defn,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)
        stk_defn.update_resource_data(stack.defn, ass.name, ass.node_data())

        # change AllocationId to EIP
        props = copy.deepcopy(ass.properties.data)
        update_eip = '11.0.0.2'
        props['EIP'] = update_eip
        props.pop('AllocationId')
        update_snippet = rsrc_defn.ResourceDefinition(ass.name, ass.type(),
                                                      stack.t.parse(stack.defn,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)

    def test_update_association_needs_update_InstanceId(self):
        server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get', return_value=server)
        iface = self.mock_interface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                    '1.2.3.4')
        self.patchobject(server, 'interface_list', return_value=[iface])
        self.mock_create_floatingip()
        self.mock_list_floatingips()
        t = template_format.parse(eip_template_ipassoc)
        stack = utils.parse_stack(t)
        self.create_eip(t, stack, 'IPAddress')
        before_props = {'InstanceId': {'Ref': 'WebServer'},
                        'EIP': '11.0.0.1'}
        after_props = {'InstanceId': {'Ref': 'WebServer2'},
                       'EIP': '11.0.0.1'}
        before = self.create_association(t, stack, 'IPAssoc')
        after = rsrc_defn.ResourceDefinition(before.name, before.type(),
                                             after_props)
        self.assertTrue(resource.UpdateReplace,
                        before._needs_update(after, before, after_props,
                                             before_props, None))

    def test_update_association_needs_update_InstanceId_EIP(self):
        server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get', return_value=server)
        iface = self.mock_interface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                    '1.2.3.4')
        self.patchobject(server, 'interface_list', return_value=[iface])
        self.mock_list_floatingips()
        self.mock_create_floatingip()

        t = template_format.parse(eip_template_ipassoc)
        stack = utils.parse_stack(t)
        self.create_eip(t, stack, 'IPAddress')
        after_props = {'InstanceId': '5678',
                       'EIP': '11.0.0.2'}
        before = self.create_association(t, stack, 'IPAssoc')
        after = rsrc_defn.ResourceDefinition(before.name, before.type(),
                                             after_props)
        updater = scheduler.TaskRunner(before.update, after)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_update_association_with_NetworkInterfaceId_or_InstanceId(self):
        server = self.fc.servers.list()[0]
        self.patchobject(self.fc.servers, 'get', return_value=server)
        iface = self.mock_interface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                    '1.2.3.4')
        self.patchobject(server, 'interface_list', return_value=[iface])
        self.mock_create_floatingip()
        self.mock_list_ports()
        self.mock_show_network()
        self.mock_no_router_for_vpc()

        t = template_format.parse(eip_template_ipassoc2)
        stack = utils.parse_stack(t)
        self.create_eip(t, stack, 'the_eip')
        ass = self.create_association(t, stack, 'IPAssoc')

        upd_server = self.fc.servers.list()[1]
        self.patchobject(self.fc.servers, 'get', return_value=upd_server)
        self.mock_list_instance_ports()

        # update with the new NetworkInterfaceId
        props = copy.deepcopy(ass.properties.data)
        update_networkInterfaceId = 'a000228d-b40b-4124-8394-a4082ae1b76b'
        props['NetworkInterfaceId'] = update_networkInterfaceId

        update_snippet = rsrc_defn.ResourceDefinition(ass.name, ass.type(),
                                                      stack.t.parse(stack.defn,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)

        # update with the InstanceId
        props = copy.deepcopy(ass.properties.data)
        instance_id = '5678'
        props.pop('NetworkInterfaceId')
        props['InstanceId'] = instance_id

        update_snippet = rsrc_defn.ResourceDefinition(ass.name, ass.type(),
                                                      stack.t.parse(stack.defn,
                                                                    props))
        scheduler.TaskRunner(ass.update, update_snippet)()
        self.assertEqual((ass.UPDATE, ass.COMPLETE), ass.state)

    def test_eip_allocation_refid_resource_name(self):
        t = template_format.parse(eip_template_ipassoc)
        stack = utils.parse_stack(t)
        rsrc = stack['IPAssoc']
        rsrc.id = '123'
        rsrc.uuid = '9bfb9456-3fe8-41f4-b318-9dba18eeef74'
        rsrc.action = 'CREATE'
        expected = '%s-%s-%s' % (rsrc.stack.name,
                                 rsrc.name,
                                 short_id.get_id(rsrc.uuid))
        self.assertEqual(expected, rsrc.FnGetRefId())

    def test_eip_allocation_refid_resource_id(self):
        t = template_format.parse(eip_template_ipassoc)
        stack = utils.parse_stack(t)
        rsrc = stack['IPAssoc']
        rsrc.resource_id = 'phy-rsrc-id'
        self.assertEqual('phy-rsrc-id', rsrc.FnGetRefId())

    def test_eip_allocation_refid_convergence_cache_data(self):
        t = template_format.parse(eip_template_ipassoc)
        cache_data = {'IPAssoc': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'convg_xyz'
        })}
        stack = utils.parse_stack(t, cache_data=cache_data)
        rsrc = stack.defn['IPAssoc']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())
