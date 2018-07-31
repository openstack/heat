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

import mock

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.openstack.manila import share_network
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


stack_template = """
heat_template_version: 2015-04-30
resources:
  share_network:
    type: OS::Manila::ShareNetwork
    properties:
      name: 1
      description: 2
      neutron_network: 3
      neutron_subnet: 4
      security_services: [6, 7]
"""


class DummyShareNetwork(object):
    def __init__(self):
        self.id = '42'
        self.segmentation_id = '2'
        self.cidr = '3'
        self.ip_version = '5'
        self.network_type = '6'


class ShareNetworkWithNova(share_network.ManilaShareNetwork):
    def is_using_neutron(self):
        return False


class ManilaShareNetworkTest(common.HeatTestCase):

    def setUp(self):
        super(ManilaShareNetworkTest, self).setUp()

        self.tmpl = template_format.parse(stack_template)
        self.stack = utils.parse_stack(self.tmpl)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['share_network']

        self.client = mock.Mock()
        self.patchobject(share_network.ManilaShareNetwork, 'client',
                         return_value=self.client)
        self.client_plugin = mock.MagicMock()

        def resolve_neutron(resource_type, name):
            return name

        self.client_plugin.find_resourceid_by_name_or_id.side_effect = (
            resolve_neutron
        )

        self.patchobject(share_network.ManilaShareNetwork, 'client_plugin',
                         return_value=self.client_plugin)

        def return_network(name):
            return '3'

        self.client_plugin.network_id_from_subnet_id.side_effect = (
            return_network
        )
        self.stub_NetworkConstraint_validate()
        self.stub_SubnetConstraint_validate()

    def _create_network(self, name, snippet, stack, use_neutron=True):
        if not use_neutron:
            net = ShareNetworkWithNova(name, snippet, stack)
        else:
            net = share_network.ManilaShareNetwork(name, snippet, stack)
        self.client.share_networks.create.return_value = DummyShareNetwork()
        self.client.share_networks.get.return_value = DummyShareNetwork()

        def get_security_service(id):
            return mock.Mock(id=id)

        self.client_plugin.get_security_service.side_effect = (
            get_security_service)

        scheduler.TaskRunner(net.create)()
        return net

    def test_create(self, rsrc_defn=None, stack=None):
        if rsrc_defn is None:
            rsrc_defn = self.rsrc_defn
        if stack is None:
            stack = self.stack
        net = self._create_network('share_network', rsrc_defn, stack)
        self.assertEqual((net.CREATE, net.COMPLETE), net.state)
        self.assertEqual('42', net.resource_id)
        net.client().share_networks.create.assert_called_with(
            name='1', description='2', neutron_net_id='3',
            neutron_subnet_id='4', nova_net_id=None)
        calls = [mock.call('42', '6'), mock.call('42', '7')]
        net.client().share_networks.add_security_service.assert_has_calls(
            calls, any_order=True)
        self.assertEqual('share_networks', net.entity)

    def test_create_with_nova(self):
        t = template_format.parse(stack_template)
        t['resources']['share_network']['properties']['nova_network'] = 'n'
        del t['resources']['share_network']['properties']['neutron_network']
        del t['resources']['share_network']['properties']['neutron_subnet']
        stack = utils.parse_stack(t)
        rsrc_defn = stack.t.resource_definitions(stack)['share_network']
        net = self._create_network('share_network', rsrc_defn, stack,
                                   use_neutron=False)
        self.assertEqual((net.CREATE, net.COMPLETE), net.state)
        self.assertEqual('42', net.resource_id)
        net.client().share_networks.create.assert_called_with(
            name='1', description='2', neutron_net_id=None,
            neutron_subnet_id=None, nova_net_id='n')
        calls = [mock.call('42', '6'), mock.call('42', '7')]
        net.client().share_networks.add_security_service.assert_has_calls(
            calls, any_order=True)
        self.assertEqual('share_networks', net.entity)

    def test_create_without_network(self):
        t = template_format.parse(stack_template)
        del t['resources']['share_network']['properties']['neutron_network']
        stack = utils.parse_stack(t)
        rsrc_defn = stack.t.resource_definitions(stack)['share_network']
        net = self._create_network('share_network', rsrc_defn, stack)
        self.assertEqual((net.CREATE, net.COMPLETE), net.state)
        self.assertEqual('42', net.resource_id)
        net.client().share_networks.create.assert_called_with(
            name='1', description='2', neutron_net_id='3',
            neutron_subnet_id='4', nova_net_id=None)
        calls = [mock.call('42', '6'), mock.call('42', '7')]
        net.client().share_networks.add_security_service.assert_has_calls(
            calls, any_order=True)
        self.assertEqual('share_networks', net.entity)

    def test_create_fail(self):
        self.client_plugin.is_conflict.return_value = False
        self.client.share_networks.add_security_service.side_effect = Exception
        self.assertRaises(
            exception.ResourceFailure,
            self._create_network, 'share_network', self.rsrc_defn, self.stack)
        csn = self.client.share_networks
        csn.create.assert_called_with(
            name='1', description='2', neutron_net_id='3',
            neutron_subnet_id='4', nova_net_id=None)
        csn.add_security_service.assert_called_once_with('42', '6')

    def test_validate_conflicting_net_subnet(self):
        t = template_format.parse(stack_template)
        t['resources']['share_network']['properties']['neutron_network'] = '5'
        stack = utils.parse_stack(t)
        rsrc_defn = stack.t.resource_definitions(stack)['share_network']
        net = self._create_network('share_network', rsrc_defn, stack)
        net.is_using_neutron = mock.Mock(return_value=True)
        msg = ('Provided neutron_subnet does not belong '
               'to provided neutron_network.')
        self.assertRaisesRegex(exception.StackValidationFailed, msg,
                               net.validate)

    def test_update(self):
        net = self._create_network('share_network', self.rsrc_defn, self.stack)
        props = self.tmpl['resources']['share_network']['properties'].copy()
        props['name'] = 'a'
        props['description'] = 'b'
        props['neutron_network'] = 'c'
        props['neutron_subnet'] = 'd'
        props['security_services'] = ['7', '8']
        update_template = net.t.freeze(properties=props)
        scheduler.TaskRunner(net.update, update_template)()
        self.assertEqual((net.UPDATE, net.COMPLETE), net.state)

        exp_args = {
            'name': 'a',
            'description': 'b',
            'neutron_net_id': 'c',
            'neutron_subnet_id': 'd',
            'nova_net_id': None
        }
        net.client().share_networks.update.assert_called_with('42', **exp_args)
        net.client().share_networks.add_security_service.assert_called_with(
            '42', '8')
        net.client().share_networks.remove_security_service.assert_called_with(
            '42', '6')

    def test_update_security_services(self):
        net = self._create_network('share_network', self.rsrc_defn, self.stack)
        props = self.tmpl['resources']['share_network']['properties'].copy()
        props['security_services'] = ['7', '8']
        update_template = net.t.freeze(properties=props)
        scheduler.TaskRunner(net.update, update_template)()
        self.assertEqual((net.UPDATE, net.COMPLETE), net.state)
        called = net.client().share_networks.update.called
        self.assertFalse(called)
        net.client().share_networks.add_security_service.assert_called_with(
            '42', '8')
        net.client().share_networks.remove_security_service.assert_called_with(
            '42', '6')

    def test_update_fail(self):
        net = self._create_network('share_network', self.rsrc_defn, self.stack)
        self.client.share_networks.remove_security_service.side_effect = (
            Exception())
        props = self.tmpl['resources']['share_network']['properties'].copy()
        props['security_services'] = []
        update_template = net.t.freeze(properties=props)
        run = scheduler.TaskRunner(net.update, update_template)
        self.assertRaises(exception.ResourceFailure, run)

    def test_nova_net_neutron_net_conflict(self):
        t = template_format.parse(stack_template)
        t['resources']['share_network']['properties']['nova_network'] = 1
        stack = utils.parse_stack(t)
        rsrc_defn = stack.t.resource_definitions(stack)['share_network']
        net = self._create_network('share_network', rsrc_defn, stack)
        msg = ('Cannot define the following properties at the same time: '
               'neutron_network, nova_network.')
        self.assertRaisesRegex(exception.ResourcePropertyConflict, msg,
                               net.validate)

    def test_nova_net_neutron_subnet_conflict(self):
        t = template_format.parse(stack_template)
        t['resources']['share_network']['properties']['nova_network'] = 1
        del t['resources']['share_network']['properties']['neutron_network']
        stack = utils.parse_stack(t)
        rsrc_defn = stack.t.resource_definitions(stack)['share_network']
        net = self._create_network('share_network', rsrc_defn, stack)
        msg = ('Cannot define the following properties at the same time: '
               'neutron_subnet, nova_network.')
        self.assertRaisesRegex(exception.ResourcePropertyConflict, msg,
                               net.validate)

    def test_nova_net_while_using_neutron(self):
        t = template_format.parse(stack_template)
        t['resources']['share_network']['properties']['nova_network'] = 'n'
        del t['resources']['share_network']['properties']['neutron_network']
        del t['resources']['share_network']['properties']['neutron_subnet']
        stack = utils.parse_stack(t)
        rsrc_defn = stack.t.resource_definitions(stack)['share_network']
        net = self._create_network('share_network', rsrc_defn, stack)
        net.is_using_neutron = mock.Mock(return_value=True)
        msg = ('With Neutron enabled you need to pass Neutron network '
               'and Neutron subnet instead of Nova network')
        self.assertRaisesRegex(exception.StackValidationFailed, msg,
                               net.validate)

    def test_neutron_net_without_neutron_subnet(self):
        t = template_format.parse(stack_template)
        del t['resources']['share_network']['properties']['neutron_subnet']
        stack = utils.parse_stack(t)
        rsrc_defn = stack.t.resource_definitions(stack)['share_network']
        net = self._create_network('share_network', rsrc_defn, stack)
        msg = ('neutron_network cannot be specified without neutron_subnet.')
        self.assertRaisesRegex(exception.ResourcePropertyDependency, msg,
                               net.validate)

    def test_attributes(self):
        net = self._create_network('share_network', self.rsrc_defn,
                                   self.stack)
        self.assertEqual('2', net.FnGetAtt('segmentation_id'))
        self.assertEqual('3', net.FnGetAtt('cidr'))
        self.assertEqual('5', net.FnGetAtt('ip_version'))
        self.assertEqual('6', net.FnGetAtt('network_type'))

    def test_get_live_state(self):
        net = self._create_network('share_network', self.rsrc_defn,
                                   self.stack)

        value = mock.MagicMock()
        value.to_dict.return_value = {
            'name': 'test',
            'segmentation_id': '123',
            'created_at': '2016-02-02T18:40:24.000000',
            'neutron_subnet_id': None,
            'updated_at': None,
            'network_type': None,
            'neutron_net_id': '4321',
            'ip_version': None,
            'nova_net_id': None,
            'cidr': None,
            'project_id': '221b4f51e9bd4f659845f657a3051a46',
            'id': '4000d1c7-1017-4ea2-a4a1-951d8b63857a',
            'description': None}

        self.client.share_networks.get.return_value = value
        self.client.security_services.list.return_value = [mock.Mock(id='6'),
                                                           mock.Mock(id='7')]

        reality = net.get_live_state(net.properties)
        expected = {
            'name': 'test',
            'neutron_subnet': None,
            'neutron_network': '4321',
            'nova_network': None,
            'description': None,
            'security_services': ['6', '7']
        }

        self.assertEqual(expected, reality)
