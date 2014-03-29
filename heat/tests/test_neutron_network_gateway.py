
# Copyright 2013 NTT Corp.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from mox import IgnoreArg
from testtools import skipIf

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine.resources.neutron import network_gateway
from heat.engine import scheduler
from heat.openstack.common.importutils import try_import
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils

neutronclient = try_import('neutronclient.v2_0.client')
neutronV20 = try_import('neutronclient.neutron.v2_0')

qe = try_import('neutronclient.common.exceptions')

gw_template = '''
{
  'AWSTemplateFormatVersion': '2010-09-09',
  'Description': 'Template to test Network Gateway resource',
  'Parameters': {},
  'Resources': {
    'NetworkGateway': {
      'Type': 'OS::Neutron::NetworkGateway',
      'Properties': {
        'name': 'NetworkGateway',
        'devices': [{
          'id': 'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
          'interface_name': 'breth1'}],
        'connections': [{
          'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
          'segmentation_type': 'vlan',
          'segmentation_id': 10}]
      }
    }
  }
}
'''

sng = {
    'network_gateway': {
        'id': 'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
        'name': 'NetworkGateway',
        'default': False,
        'tenant_id': '96ba52dc-c5c5-44c6-9a9d-d3ba1a03f77f',
        'devices': [{
            'id': 'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
            'interface_name': 'breth1'}],
        'ports': [{
            'segmentation_type': 'vlan',
            'port_id': '32acc49c-899e-44ea-8177-6f4157e12eb4',
            'segmentation_id': 10}]
    }
}


@skipIf(neutronclient is None, 'neutronclient unavailable')
class NeutronNetworkGatewayTest(HeatTestCase):
    @skipIf(neutronV20 is None, 'Missing Neutron v2_0')
    def setUp(self):
        super(NeutronNetworkGatewayTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_network_gateway')
        self.m.StubOutWithMock(neutronclient.Client, 'show_network_gateway')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_network_gateway')
        self.m.StubOutWithMock(neutronclient.Client, 'connect_network_gateway')
        self.m.StubOutWithMock(neutronclient.Client, 'update_network_gateway')
        self.m.StubOutWithMock(neutronclient.Client,
                               'disconnect_network_gateway')
        self.m.StubOutWithMock(neutronclient.Client, 'list_networks')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def prepare_create_network_gateway(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_network_gateway({
            'network_gateway': {
                'name': u'NetworkGateway',
                'devices': [{'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                             'interface_name': u'breth1'}]
            }
        }
        ).AndReturn({
            'network_gateway': {
                'id': 'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                'name': 'NetworkGateway',
                'default': False,
                'tenant_id': '96ba52dc-c5c5-44c6-9a9d-d3ba1a03f77f',
                'devices': [{
                    'id': 'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                    'interface_name': 'breth1'}]
            }
        }
        )
        neutronclient.Client.connect_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': u'vlan'
            }
        ).AndReturn({
            'connection_info': {
                'network_gateway_id': u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'port_id': u'32acc49c-899e-44ea-8177-6f4157e12eb4'
            }
        })

        t = template_format.parse(gw_template)
        stack = utils.parse_stack(t)
        rsrc = network_gateway.NetworkGateway(
            'test_network_gateway',
            t['Resources']['NetworkGateway'], stack)
        return rsrc

    def test_network_gateway_create(self):
        rsrc = self.prepare_create_network_gateway()

        neutronclient.Client.disconnect_network_gateway(
            'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': u'vlan'
            }
        ).AndReturn(None)

        neutronclient.Client.disconnect_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': u'vlan'
            }
        ).AndReturn(qe.NeutronClientException(status_code=404))

        neutronclient.Client.delete_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37'
        ).AndReturn(None)

        neutronclient.Client.show_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37'
        ).AndReturn(sng)

        neutronclient.Client.show_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37'
        ).AndRaise(qe.NeutronClientException(status_code=404))

        neutronclient.Client.delete_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37'
        ).AndRaise(qe.NeutronClientException(status_code=404))

        self.m.ReplayAll()

        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        ref_id = rsrc.FnGetRefId()
        self.assertEqual(u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', ref_id)

        self.assertRaises(
            exception.InvalidTemplateAttribute, rsrc.FnGetAtt, 'Foo')

        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_network_gateway_update(self):
        rsrc = self.prepare_create_network_gateway()

        neutronclient.Client.update_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_gateway': {
                    'name': u'NetworkGatewayUpdate'
                }
            }
        ).AndReturn(None)

        neutronclient.Client.disconnect_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': u'vlan'
            }
        ).AndReturn(None)

        neutronclient.Client.connect_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 0,
                'segmentation_type': u'flat'
            }
        ).AndReturn({
            'connection_info': {
                'network_gateway_id': u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'port_id': u'aa800972-f6be-4c65-8453-9ab31834bf80'
            }
        })

        neutronclient.Client.disconnect_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': u'vlan'
            }
        ).AndRaise(qe.NeutronClientException(status_code=404))

        neutronclient.Client.connect_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 0,
                'segmentation_type': u'flat'
            }
        ).AndReturn({
            'connection_info': {
                'network_gateway_id': u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'port_id': u'aa800972-f6be-4c65-8453-9ab31834bf80'
            }
        })

        neutronclient.Client.disconnect_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': u'vlan'
            }
        ).AndReturn(None)

        neutronclient.Client.delete_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37'
        ).AndReturn(None)

        neutronclient.Client.create_network_gateway({
            'network_gateway': {
                'name': u'NetworkGateway',
                'devices': [{'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                             'interface_name': u'breth2'}]
            }
        }
        ).AndReturn({
            'network_gateway': {
                'id': 'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                'name': 'NetworkGateway',
                'default': False,
                'tenant_id': '96ba52dc-c5c5-44c6-9a9d-d3ba1a03f77f',
                'devices': [{
                    'id': 'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                    'interface_name': 'breth2'}]
            }
        }
        )

        neutronclient.Client.connect_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': u'vlan'
            }
        ).AndReturn({
            'connection_info': {
                'network_gateway_id': u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'port_id': u'aa800972-f6be-4c65-8453-9ab31834bf80'
            }
        })

        self.m.ReplayAll()

        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # update name
        snippet_for_update = {
            'Type': u'OS::Neutron::NetworkGatewayUpdate',
            'Properties': {
                'name': u'NetworkGatewayUpdate',
                'devices': [{
                    'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                    'interface_name': u'breth1'}],
                'connections': [{
                    'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                    'segmentation_type': 'vlan',
                    'segmentation_id': 10}]
            }
        }
        prop_diff = {'name': u'NetworkGatewayUpdate'}
        self.assertIsNone(rsrc.handle_update(snippet_for_update, IgnoreArg(),
                                             prop_diff))

        # update connections
        snippet_for_update = {
            'Type': u'OS::Neutron::NetworkGateway',
            'Properties': {
                'name': u'NetworkGateway',
                'devices': [{
                    'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                    'interface_name': u'breth1'}],
                'connections': [{
                    'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                    'segmentation_type': u'flat',
                    'segmentation_id': 0}]
            }
        }
        prop_diff = {
            'connections': [{
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_type': u'flat',
                'segmentation_id': 0}]
        }
        self.assertIsNone(rsrc.handle_update(snippet_for_update, IgnoreArg(),
                                             prop_diff))

        # update connections once more
        self.assertIsNone(rsrc.handle_update(snippet_for_update, IgnoreArg(),
                                             prop_diff))

        # update devices
        snippet_for_update = {
            'Type': u'OS::Neutron::NetworkGateway',
            'Properties': {
                'name': u'NetworkGateway',
                'devices': [{
                    'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                    'interface_name': u'breth2'}],
                'connections': [{
                    'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                    'segmentation_type': u'vlan',
                    'segmentation_id': 10}]
            }
        }
        prop_diff = {
            'devices': [{
                'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                'interface_name': u'breth2'}]
        }
        self.assertIsNone(rsrc.handle_update(snippet_for_update, IgnoreArg(),
                                             prop_diff))

        self.m.VerifyAll()

    def test_network_gatway_create_failed(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_network_gateway({
            'network_gateway': {
                'name': u'NetworkGateway',
                'devices': [{
                    'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                    'interface_name': u'breth1'}]
            }
        }
        ).AndRaise(network_gateway.NeutronClientException)

        self.m.ReplayAll()

        t = template_format.parse(gw_template)
        stack = utils.parse_stack(t)
        rsrc = network_gateway.NetworkGateway(
            'network_gateway', t['Resources']['NetworkGateway'], stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            str(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_gateway_validate_failed_with_vlan(self):
        t = template_format.parse(gw_template)
        del t['Resources']['NetworkGateway']['Properties'][
            'connections'][0]['segmentation_id']
        stack = utils.parse_stack(t)
        rsrc = network_gateway.NetworkGateway(
            'test_network_gateway',
            t['Resources']['NetworkGateway'], stack)

        self.m.ReplayAll()

        error = self.assertRaises(exception.StackValidationFailed,
                                  scheduler.TaskRunner(rsrc.validate))

        self.assertEqual(
            'segmentation_id must be specified for using vlan',
            str(error))

        self.m.VerifyAll()

    def test_gateway_validate_failed_with_flat(self):
        t = template_format.parse(gw_template)
        t['Resources']['NetworkGateway']['Properties'][
            'connections'][0]['segmentation_type'] = 'flat'
        stack = utils.parse_stack(t)
        rsrc = network_gateway.NetworkGateway(
            'test_network_gateway',
            t['Resources']['NetworkGateway'], stack)

        self.m.ReplayAll()

        error = self.assertRaises(exception.StackValidationFailed,
                                  scheduler.TaskRunner(rsrc.validate))

        self.assertEqual(
            'segmentation_id cannot be specified except 0 for using flat',
            str(error))

        self.m.VerifyAll()

    def test_network_gateway_attribute(self):
        neutronclient.Client.show_network_gateway(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37'
        ).MultipleTimes().AndReturn(sng)
        rsrc = self.prepare_create_network_gateway()
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual(u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                         rsrc.FnGetRefId())
        self.assertEqual(False, rsrc.FnGetAtt('default'))

        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'hoge')
        self.assertEqual(
            'The Referenced Attribute (test_network_gateway hoge) is '
            'incorrect.', str(error))

        self.m.VerifyAll()
