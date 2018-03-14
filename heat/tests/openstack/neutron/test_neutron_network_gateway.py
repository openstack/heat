#
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

import mock
import six

from neutronclient.common import exceptions as qe
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient

from heat.common import exception
from heat.common import template_format
from heat.common import timeutils
from heat.engine.resources.openstack.neutron import network_gateway
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


gw_template_deprecated = '''
heat_template_version: 2015-04-30
description: Template to test Network Gateway resource
resources:
  NetworkGateway:
    type: OS::Neutron::NetworkGateway
    properties:
      name: NetworkGateway
      devices:
        - id: e52148ca-7db9-4ec3-abe6-2c7c0ff316eb
          interface_name: breth1
      connections:
        - network_id: 6af055d3-26f6-48dd-a597-7611d7e58d35
          segmentation_type: vlan
          segmentation_id: 10
'''

gw_template = '''
heat_template_version: 2015-04-30
description: Template to test Network Gateway resource
resources:
  NetworkGateway:
    type: OS::Neutron::NetworkGateway
    properties:
      name: NetworkGateway
      devices:
        - id: e52148ca-7db9-4ec3-abe6-2c7c0ff316eb
          interface_name: breth1
      connections:
        - network: 6af055d3-26f6-48dd-a597-7611d7e58d35
          segmentation_type: vlan
          segmentation_id: 10
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


class NeutronNetworkGatewayTest(common.HeatTestCase):
    def setUp(self):
        super(NeutronNetworkGatewayTest, self).setUp()
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)
        self.patchobject(neutronV20, 'find_resourceid_by_name_or_id',
                         return_value='6af055d3-26f6-48dd-a597-7611d7e58d35')

    def mock_create_fail_network_not_found_delete_success(self):
        self.mockclient.create_network_gateway.return_value = {
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
        self.mockclient.connect_network_gateway.side_effect = (
            qe.NeutronClientException)
        self.mockclient.disconnect_network_gateway.return_value = None
        # mock successful to delete the network_gateway
        self.mockclient.delete_network_gateway.return_value = None
        self.mockclient.show_network_gateway.side_effect = (
            qe.NeutronClientException(status_code=404))

        t = template_format.parse(gw_template)

        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = network_gateway.NetworkGateway(
            'test_network_gateway',
            resource_defns['NetworkGateway'], self.stack)
        return rsrc

    def prepare_create_network_gateway(self, resolve_neutron=True):
        self.mockclient.create_network_gateway.return_value = {
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
        self.mockclient.connect_network_gateway.return_value = {
            'connection_info': {
                'network_gateway_id': 'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'port_id': '32acc49c-899e-44ea-8177-6f4157e12eb4'
            }
        }
        self.stub_NetworkConstraint_validate()
        if resolve_neutron:
            t = template_format.parse(gw_template)
        else:
            t = template_format.parse(gw_template_deprecated)

        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = network_gateway.NetworkGateway(
            'test_network_gateway',
            resource_defns['NetworkGateway'], self.stack)
        return rsrc

    def _test_network_gateway_create(self, resolve_neutron=True):
        rsrc = self.prepare_create_network_gateway(resolve_neutron)
        self.mockclient.disconnect_network_gateway.side_effect = [
            None,
            qe.NeutronClientException(status_code=404),
            qe.NeutronClientException(status_code=404),
        ]
        self.mockclient.delete_network_gateway.side_effect = [
            None,
            None,
            qe.NeutronClientException(status_code=404),
        ]
        self.mockclient.show_network_gateway.side_effect = [
            sng,
            qe.NeutronClientException(status_code=404),
        ]
        self.patchobject(timeutils, 'retry_backoff_delay', return_value=0.01)

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

        self.mockclient.create_network_gateway.assert_called_once_with({
            'network_gateway': {
                'name': 'NetworkGateway',
                'devices': [{'id': 'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                             'interface_name': 'breth1'}]
            }
        })
        self.mockclient.connect_network_gateway.assert_called_once_with(
            'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': 'vlan'
            })
        self.mockclient.disconnect_network_gateway.assert_called_with(
            'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': 'vlan'
            })
        self.mockclient.delete_network_gateway.assert_called_with(
            'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37')
        self.mockclient.show_network_gateway.assert_called_with(
            'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37')
        timeutils.retry_backoff_delay.assert_called_once_with(1,
                                                              jitter_max=2.0)

    def test_network_gateway_create_deprecated(self):
        self._test_network_gateway_create(resolve_neutron=False)

    def test_network_gateway_create(self):
        self._test_network_gateway_create()

    def test_network_gateway_create_fail_delete_success(self):
        # if network_gateway created successful, but didn't to connect with
        # network, then can delete the network_gateway successful
        # without residue network_gateway
        rsrc = self.mock_create_fail_network_not_found_delete_success()
        self.stub_NetworkConstraint_validate()

        rsrc.validate()
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.create))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        ref_id = rsrc.FnGetRefId()
        self.assertEqual(u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', ref_id)

        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_network_gateway.assert_called_once_with({
            'network_gateway': {
                'name': 'NetworkGateway',
                'devices': [{'id': 'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                             'interface_name': 'breth1'}]
            }
        })
        self.mockclient.connect_network_gateway.assert_called_once_with(
            'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': 'vlan'
            }
        )
        self.mockclient.disconnect_network_gateway.assert_called_once_with(
            'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': 'vlan'
            }
        )
        self.mockclient.delete_network_gateway.assert_called_once_with(
            'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37')
        self.mockclient.show_network_gateway.assert_called_once_with(
            'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37')

    def test_network_gateway_update(self):
        rsrc = self.prepare_create_network_gateway()
        self.mockclient.update_network_gateway.return_value = None
        self.mockclient.disconnect_network_gateway.side_effect = [
            None,
            qe.NeutronClientException(status_code=404),
            None,
        ]
        self.mockclient.connect_network_gateway.side_effect = [
            self.mockclient.connect_network_gateway.return_value,
            {
                'connection_info': {
                    'network_gateway_id':
                        'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                    'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                    'port_id': 'aa800972-f6be-4c65-8453-9ab31834bf80'
                }
            },
            {
                'connection_info': {
                    'network_gateway_id':
                        'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                    'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                    'port_id': 'aa800972-f6be-4c65-8453-9ab31834bf80'
                }
            },
            {
                'connection_info': {
                    'network_gateway_id':
                        'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                    'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                    'port_id': 'aa800972-f6be-4c65-8453-9ab31834bf80'
                }
            },
            {
                'connection_info': {
                    'network_gateway_id':
                        'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                    'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                    'port_id': 'aa800972-f6be-4c65-8453-9ab31834bf80'
                }
            },
        ]
        self.mockclient.delete_network_gateway.return_value = None

        self.mockclient.create_network_gateway.side_effect = [
            self.mockclient.create_network_gateway.return_value,
            {
                'network_gateway': {
                    'id': 'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                    'name': 'NetworkGateway',
                    'default': False,
                    'tenant_id': '96ba52dc-c5c5-44c6-9a9d-d3ba1a03f77f',
                    'devices': [{
                        'id': 'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                        'interface_name': 'breth2'}]
                }
            },
        ]

        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # update name
        snippet_for_update1 = rsrc_defn.ResourceDefinition(
            rsrc.name,
            rsrc.type(),
            {
                'name': u'NetworkGatewayUpdate',
                'devices': [{
                    'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                    'interface_name': u'breth1'}],
                'connections': [{
                    'network': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                    'segmentation_type': 'vlan',
                    'segmentation_id': 10}]
            })
        scheduler.TaskRunner(rsrc.update, snippet_for_update1)()

        # update connections
        snippet_for_update2 = rsrc_defn.ResourceDefinition(
            rsrc.name,
            rsrc.type(),
            {
                'name': u'NetworkGatewayUpdate',
                'devices': [{
                    'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                    'interface_name': u'breth1'}],
                'connections': [{
                    'network': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                    'segmentation_type': u'flat',
                    'segmentation_id': 0}]
            })
        scheduler.TaskRunner(rsrc.update, snippet_for_update2,
                             snippet_for_update1)()

        # update connections once more
        snippet_for_update3 = rsrc_defn.ResourceDefinition(
            rsrc.name,
            rsrc.type(),
            {
                'name': u'NetworkGatewayUpdate',
                'devices': [{
                    'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                    'interface_name': u'breth1'}],
                'connections': [{
                    'network': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                    'segmentation_type': u'flat',
                    'segmentation_id': 1}]
            })
        scheduler.TaskRunner(rsrc.update, snippet_for_update3,
                             snippet_for_update2)()

        # update devices
        snippet_for_update4 = rsrc_defn.ResourceDefinition(
            rsrc.name,
            rsrc.type(),
            {
                'name': u'NetworkGatewayUpdate',
                'devices': [{
                    'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                    'interface_name': u'breth2'}],
                'connections': [{
                    'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                    'segmentation_type': u'vlan',
                    'segmentation_id': 10}]
            })
        scheduler.TaskRunner(rsrc.update, snippet_for_update4,
                             snippet_for_update3)()

        self.mockclient.create_network_gateway.assert_has_calls([
            mock.call({
                'network_gateway': {
                    'name': 'NetworkGateway',
                    'devices': [{'id': 'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                                 'interface_name': 'breth1'}]
                }
            }),
            mock.call({
                'network_gateway': {
                    'name': u'NetworkGatewayUpdate',
                    'devices': [{'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                                 'interface_name': u'breth2'}]
                }
            }),
        ])
        self.mockclient.connect_network_gateway.assert_has_calls([
            mock.call('ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': 'vlan'
            }),
            mock.call('ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 0,
                'segmentation_type': 'flat'
            }),
            mock.call('ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 1,
                'segmentation_type': 'flat'
            }),
            mock.call('ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 1,
                'segmentation_type': u'flat'
            }),
        ])
        self.mockclient.update_network_gateway.assert_has_calls([
            mock.call('ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_gateway': {
                    'name': 'NetworkGatewayUpdate'
                }
            }),
        ])
        self.mockclient.disconnect_network_gateway.assert_has_calls([
            mock.call('ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': 'vlan'
            }),
            mock.call('ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 0,
                'segmentation_type': 'flat'
            }),
            mock.call('ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 1,
                'segmentation_type': 'flat'
            }),
        ])
        self.mockclient.delete_network_gateway.assert_called_once_with(
            'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37')

    def test_network_gatway_create_failed(self):
        self.mockclient.create_network_gateway.side_effect = (
            qe.NeutronClientException)
        self.stub_NetworkConstraint_validate()

        t = template_format.parse(gw_template)
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = network_gateway.NetworkGateway(
            'network_gateway', resource_defns['NetworkGateway'], stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.network_gateway: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_network_gateway.assert_called_once_with({
            'network_gateway': {
                'name': u'NetworkGateway',
                'devices': [{
                    'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                    'interface_name': u'breth1'}]
            }
        })

    def test_gateway_validate_failed_with_vlan(self):
        t = template_format.parse(gw_template)
        del t['resources']['NetworkGateway']['properties'][
            'connections'][0]['segmentation_id']
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = network_gateway.NetworkGateway(
            'test_network_gateway',
            resource_defns['NetworkGateway'], stack)
        self.stub_NetworkConstraint_validate()

        error = self.assertRaises(exception.StackValidationFailed,
                                  scheduler.TaskRunner(rsrc.validate))

        self.assertEqual(
            'segmentation_id must be specified for using vlan',
            six.text_type(error))

    def test_gateway_validate_failed_with_flat(self):
        t = template_format.parse(gw_template)
        t['resources']['NetworkGateway']['properties'][
            'connections'][0]['segmentation_type'] = 'flat'
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = network_gateway.NetworkGateway(
            'test_network_gateway',
            resource_defns['NetworkGateway'], stack)
        self.stub_NetworkConstraint_validate()

        error = self.assertRaises(exception.StackValidationFailed,
                                  scheduler.TaskRunner(rsrc.validate))

        self.assertEqual(
            'segmentation_id cannot be specified except 0 for using flat',
            six.text_type(error))

    def test_network_gateway_attribute(self):
        rsrc = self.prepare_create_network_gateway()
        self.mockclient.show_network_gateway.return_value = sng

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual(u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37',
                         rsrc.FnGetRefId())
        self.assertFalse(rsrc.FnGetAtt('default'))

        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'hoge')
        self.assertEqual(
            'The Referenced Attribute (test_network_gateway hoge) is '
            'incorrect.', six.text_type(error))

        self.mockclient.create_network_gateway.assert_called_once_with({
            'network_gateway': {
                'name': u'NetworkGateway',
                'devices': [{'id': u'e52148ca-7db9-4ec3-abe6-2c7c0ff316eb',
                             'interface_name': u'breth1'}]
            }
        })
        self.mockclient.connect_network_gateway.assert_called_once_with(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37', {
                'network_id': u'6af055d3-26f6-48dd-a597-7611d7e58d35',
                'segmentation_id': 10,
                'segmentation_type': u'vlan'
            })
        self.mockclient.show_network_gateway.assert_called_with(
            u'ed4c03b9-8251-4c09-acc4-e59ee9e6aa37')
