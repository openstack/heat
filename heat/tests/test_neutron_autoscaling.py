
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

import mox
from oslo.config import cfg
from testtools import skipIf

from heat.common import template_format
from heat.db import api as db_api
from heat.engine import clients
from heat.engine import environment
from heat.engine import parser
from heat.engine.resources import image
from heat.engine.resources import instance
from heat.engine.resources import nova_utils
from heat.engine import template
from heat.openstack.common.importutils import try_import
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils
from heat.tests.v1_1 import fakes as v1fakes


neutroncli = try_import('neutronclient')

as_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "AutoScaling Test",
  "Parameters" : {
  "ImageId": {"Type": "String"},
  "KeyName": {"Type": "String"},
  "SubnetId": {"Type": "String"}
  },
  "Resources" : {
    "SvrGrp" : {
      "Type" : "AWS::AutoScaling::AutoScalingGroup",
      "Properties" : {
        "AvailabilityZones" : ["nova"],
        "LaunchConfigurationName" : { "Ref" : "LaunchConfig" },
        "MinSize" : "1",
        "MaxSize" : "5",
        "DesiredCapacity": "1",
        "VPCZoneIdentifier": [ { "Ref": "SubnetId" } ],
        "LoadBalancerNames" : [ { "Ref" : "ElasticLoadBalancer" } ]
      }
    },
    "myMonitor": {
        "Type": "OS::Neutron::HealthMonitor",
        "Properties": {
            "type": "HTTP",
            "delay": 3,
            "max_retries": 5,
            "timeout": 10
        }
    },
    "myPool": {
        "Type": "OS::Neutron::Pool",
        "Properties": {
            "description": "Test Pool",
            "lb_method": "ROUND_ROBIN",
            "monitors": [ { "Ref": "myMonitor" } ],
            "name": "Test_Pool",
            "protocol": "HTTP",
            "subnet_id": { "Ref": "SubnetId" },
            "vip": {
                "description": "Test VIP",
                "connection_limit": 1000,
                "address": "10.0.3.121",
                "protocol_port": 80,
                "name": "test_vip"
            }
        }
    },
    "ElasticLoadBalancer" : {
        'Type': 'OS::Neutron::LoadBalancer',
        'Properties': {
            'protocol_port': 8080,
            'pool_id': { "Ref": "myPool" }
        }
    },
    "LaunchConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Properties": {
        "ImageId" : {"Ref": "ImageId"},
        "InstanceType"   : "bar",
      }
    }
  }
}
'''


class AutoScalingTest(HeatTestCase):
    params = {'KeyName': 'test', 'ImageId': 'foo'}

    def setUp(self):
        super(AutoScalingTest, self).setUp()

        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()
        self.fc = v1fakes.FakeClient()

        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')

        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')

        self.m.StubOutWithMock(clients.neutronclient.Client,
                               'create_health_monitor')
        self.m.StubOutWithMock(clients.neutronclient.Client,
                               'associate_health_monitor')
        self.m.StubOutWithMock(clients.neutronclient.Client, 'create_pool')
        self.m.StubOutWithMock(clients.neutronclient.Client, 'create_vip')
        self.m.StubOutWithMock(clients.neutronclient.Client, 'show_pool')
        self.m.StubOutWithMock(clients.neutronclient.Client, 'show_vip')
        self.m.StubOutWithMock(clients.neutronclient.Client, 'create_member')
        self.m.StubOutWithMock(clients.neutronclient.Client, 'list_members')

        self.m.StubOutWithMock(nova_utils, 'server_to_ipaddress')
        self.m.StubOutWithMock(parser.Stack, 'validate')

        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        self.m.StubOutWithMock(image.ImageConstraint, "validate")

    @skipIf(neutroncli is None, 'neutronclient unavailable')
    def test_lb(self):

        tmpl = template_format.parse(as_template)

        network_body = {
            "network": {
                "id": str(uuid.uuid4()),
                "name": "testnet",
                "admin_state_up": True
            }
        }
        subnet_body = {
            "subnet": {
                "name": "testsubnet",
                "id": str(uuid.uuid4()),
                "network_id": network_body['network']['id'],
                "ip_version": 4,
                "cidr": "10.0.3.0/24",
                "allocation_pools": [
                    {
                        "start": "10.0.3.20",
                        "end": "10.0.3.150"
                    }
                ],
                "gateway_ip": "10.0.3.1"
            }
        }

        self.params["SubnetId"] = subnet_body['subnet']['id']
        mon_block = {
            'health_monitor': tmpl['Resources']['myMonitor']['Properties']
        }
        mon_block['health_monitor']['admin_state_up'] = True
        mon_ret_block = copy.deepcopy(mon_block)
        mon_ret_block['health_monitor']['id'] = str(uuid.uuid4())
        mon_ret_block['health_monitor']['status'] = 'ACTIVE'

        pool_block = {'pool': {}}
        tmp_pool_block = tmpl['Resources']['myPool']['Properties']
        for val in ['lb_method', 'protocol', 'name', 'description']:
            pool_block['pool'][val] = tmp_pool_block[val]
        pool_block['pool']['admin_state_up'] = True
        pool_block['pool']['subnet_id'] = self.params['SubnetId']
        pool_block['pool']['admin_state_up'] = True
        pool_ret_block = copy.deepcopy(pool_block)
        pool_ret_block['pool']['id'] = str(uuid.uuid4())
        pool_ret_block['pool']['status'] = 'ACTIVE'

        tmp_vip_block = tmp_pool_block.pop('vip')
        vip_block = {
            'vip': {
                'protocol': pool_block['pool']['protocol'],
                'description': tmp_vip_block['description'],
                'admin_state_up': True,
                'subnet_id': self.params['SubnetId'],
                'connection_limit': tmp_vip_block['connection_limit'],
                'pool_id': pool_ret_block['pool']['id'],
                'address': tmp_vip_block['address'],
                'protocol_port': tmp_vip_block['protocol_port'],
                'name': tmp_vip_block['name']
            }
        }
        vip_ret_block = copy.deepcopy(vip_block)
        vip_ret_block['vip']['id'] = str(uuid.uuid4())
        vip_ret_block['vip']['status'] = 'ACTIVE'

        port_block = {
            'port': {
                'network_id': network_body['network']['id'],
                'fixed_ips': [
                    {
                        'subnet_id': subnet_body['subnet']['id'],
                    }
                ],
                'admin_state_up': True
            }
        }
        port_ret_block = copy.deepcopy(port_block)
        port_ret_block['port']['id'] = str(uuid.uuid4())

        membera_block = {
            'member': {
                'protocol_port': 8080,
                'pool_id': pool_ret_block['pool']['id'],
                'address': '1.2.3.4'
            }
        }
        membera_ret_block = copy.deepcopy(membera_block)
        membera_ret_block['member']['id'] = str(uuid.uuid4())

        memberb_block = {
            'member': {
                'protocol_port': 8080,
                'pool_id': pool_ret_block['pool']['id'],
                'address': '1.2.3.5'
            }
        }
        memberb_ret_block = copy.deepcopy(memberb_block)
        memberb_ret_block['member']['id'] = str(uuid.uuid4())

        memberc_block = {
            'member': {
                'protocol_port': 8080,
                'pool_id': pool_ret_block['pool']['id'],
                'address': '1.2.3.6'
            }
        }
        memberc_ret_block = copy.deepcopy(memberc_block)
        memberc_ret_block['member']['id'] = str(uuid.uuid4())

        class id_type(object):

            def __init__(self, id, name):
                self.id = id
                self.name = name

        instances = {}

        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())

        clients.neutronclient.Client.create_health_monitor(mon_block).\
            AndReturn(mon_ret_block)

        clients.neutronclient.Client.create_pool(pool_block).\
            AndReturn(pool_ret_block)

        clients.neutronclient.Client.associate_health_monitor(
            pool_ret_block['pool']['id'],
            {'health_monitor': {
                'id': mon_ret_block['health_monitor']['id']
            }}).AndReturn(None)

        clients.neutronclient.Client.create_vip(vip_block).\
            AndReturn(vip_ret_block)

        clients.neutronclient.Client.show_pool(pool_ret_block['pool']['id']).\
            AndReturn(pool_ret_block)

        clients.neutronclient.Client.show_vip(vip_ret_block['vip']['id']).\
            AndReturn(vip_ret_block)

        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())

        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())

        parser.Stack.validate()
        instid = str(uuid.uuid4())
        instance.Instance.handle_create().AndReturn(instid)
        instance.Instance.check_create_complete(mox.IgnoreArg())\
            .AndReturn(False)
        instance.Instance.check_create_complete(mox.IgnoreArg())\
            .AndReturn(True)

        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)

        nova_utils.server_to_ipaddress(
            mox.IgnoreArg(),
            mox.IgnoreArg()).AndReturn('1.2.3.4')

        clients.neutronclient.Client.create_member(membera_block).\
            AndReturn(membera_ret_block)

        instances[instid] = membera_ret_block['member']['id']

        # Start of update
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())

        parser.Stack.validate()
        instid = str(uuid.uuid4())
        instance.Instance.handle_create().AndReturn(instid)
        instance.Instance.check_create_complete(mox.IgnoreArg())\
            .AndReturn(False)
        instance.Instance.check_create_complete(mox.IgnoreArg())\
            .AndReturn(True)
        instances[instid] = memberb_ret_block['member']['id']

        instid = str(uuid.uuid4())
        instance.Instance.handle_create().AndReturn(instid)
        instance.Instance.check_create_complete(mox.IgnoreArg())\
            .AndReturn(False)
        instance.Instance.check_create_complete(mox.IgnoreArg())\
            .AndReturn(True)

        nova_utils.server_to_ipaddress(
            mox.IgnoreArg(),
            mox.IgnoreArg()).AndReturn('1.2.3.5')

        clients.neutronclient.Client.create_member(memberb_block).\
            AndReturn(memberb_ret_block)

        nova_utils.server_to_ipaddress(
            mox.IgnoreArg(),
            mox.IgnoreArg()).AndReturn('1.2.3.6')

        clients.neutronclient.Client.create_member(memberc_block).\
            AndReturn(memberc_ret_block)

        self.m.ReplayAll()

        # Start of stack create
        env = {'parameters': self.params}
        tmpl = template_format.parse(as_template)

        stack = parser.Stack(self.ctx, 'update_test_stack',
                             template.Template(tmpl),
                             environment.Environment(env))

        stack.store()
        stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         stack.state)

        # Start of stack update
        stack2 = parser.Stack.load(self.ctx, stack_id=stack.id)

        tmpl2 = copy.deepcopy(tmpl)
        tmpl2['Resources']['SvrGrp']['Properties']['DesiredCapacity'] = '3'

        update_stack = parser.Stack(self.ctx, 'update_test_stack',
                                    template.Template(tmpl2),
                                    environment.Environment(env))
        stack2.update(update_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         stack2.state)

        members = db_api.resource_data_get_all(stack['ElasticLoadBalancer'])
        self.assertEqual(3, len(members.keys()))

        self.m.VerifyAll()
