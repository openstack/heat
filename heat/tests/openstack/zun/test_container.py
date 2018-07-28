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
import six

from oslo_config import cfg
from zunclient import exceptions as zc_exc

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.clients.os import zun
from heat.engine.resources.openstack.zun import container
from heat.engine import scheduler
from heat.engine import template
from heat.tests import common
from heat.tests import utils

zun_template = '''
heat_template_version: 2017-09-01

resources:
  test_container:
    type: OS::Zun::Container
    properties:
      name: test_container
      image: "cirros:latest"
      command: sleep 10000
      cpu: 0.1
      memory: 100
      environment:
        myenv: foo
      workdir: /testdir
      labels:
        mylabel: bar
      image_pull_policy: always
      restart_policy: on-failure:2
      interactive: false
      image_driver: docker
      hints:
        hintkey: hintval
      hostname: myhost
      security_groups:
        - my_seg
      mounts:
        - volume_size: 1
          mount_path: /data
        - volume_id: 6ec29ba3-bf2c-4276-a88e-3670ea5abc80
          mount_path: /data2
      networks:
        - network: mynet
          fixed_ip: 10.0.0.4
        - network: mynet2
          fixed_ip: fe80::3
        - port: myport
'''

zun_template_minimum = '''
heat_template_version: 2017-09-01

resources:
  test_container:
    type: OS::Zun::Container
    properties:
      name: test_container
      image: "cirros:latest"
'''


def create_fake_iface(port=None, net=None, mac=None, ip=None, subnet=None):
    class fake_interface(object):
        def __init__(self, port_id, net_id, mac_addr, fixed_ip, subnet_id):
            self.port_id = port_id
            self.net_id = net_id
            self.mac_addr = mac_addr
            self.fixed_ips = [{'ip_address': fixed_ip, 'subnet_id': subnet_id}]

    return fake_interface(port, net, mac, ip, subnet)


class ZunContainerTest(common.HeatTestCase):

    def setUp(self):
        super(ZunContainerTest, self).setUp()

        self.resource_id = '12345'
        self.fake_name = 'test_container'
        self.fake_image = 'cirros:latest'
        self.fake_command = 'sleep 10000'
        self.fake_cpu = 0.1
        self.fake_memory = 100
        self.fake_env = {'myenv': 'foo'}
        self.fake_workdir = '/testdir'
        self.fake_labels = {'mylabel': 'bar'}
        self.fake_image_policy = 'always'
        self.fake_restart_policy = {'MaximumRetryCount': '2',
                                    'Name': 'on-failure'}
        self.fake_interactive = False
        self.fake_image_driver = 'docker'
        self.fake_hints = {'hintkey': 'hintval'}
        self.fake_hostname = 'myhost'
        self.fake_security_groups = ['my_seg']
        self.fake_mounts = [
            {'volume_id': None, 'volume_size': 1, 'mount_path': '/data'},
            {'volume_id': '6ec29ba3-bf2c-4276-a88e-3670ea5abc80',
             'volume_size': None, 'mount_path': '/data2'}]
        self.fake_mounts_args = [
            {'size': 1, 'destination': '/data'},
            {'source': '6ec29ba3-bf2c-4276-a88e-3670ea5abc80',
             'destination': '/data2'}]
        self.fake_networks = [
            {'network': 'mynet', 'port': None, 'fixed_ip': '10.0.0.4'},
            {'network': 'mynet2', 'port': None, 'fixed_ip': 'fe80::3'},
            {'network': None, 'port': 'myport', 'fixed_ip': None}]
        self.fake_networks_args = [
            {'network': 'mynet', 'v4-fixed-ip': '10.0.0.4'},
            {'network': 'mynet2', 'v6-fixed-ip': 'fe80::3'},
            {'port': 'myport'}]

        self.fake_network_id = '9c11d847-99ce-4a83-82da-9827362a68e8'
        self.fake_network_name = 'private'
        self.fake_networks_attr = {
            'networks': [
                {
                    'id': self.fake_network_id,
                    'name': self.fake_network_name,
                }
            ]
        }
        self.fake_address = {
            'version': 4,
            'addr': '10.0.0.12',
            'port': 'ab5c12d8-f414-48a3-b765-8ce34a6714d2'
        }
        self.fake_addresses = {
            self.fake_network_id: [self.fake_address]
        }
        self.fake_extended_addresses = {
            self.fake_network_id: [self.fake_address],
            self.fake_network_name: [self.fake_address],
        }

        t = template_format.parse(zun_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns[self.fake_name]
        self.client = mock.Mock()
        self.patchobject(container.Container, 'client',
                         return_value=self.client)
        self.neutron_client = mock.Mock()
        self.patchobject(container.Container, 'neutron',
                         return_value=self.neutron_client)
        self.stub_VolumeConstraint_validate()
        self.mock_update = self.patchobject(zun.ZunClientPlugin,
                                            'update_container')
        self.stub_PortConstraint_validate()
        self.mock_find = self.patchobject(
            neutron.NeutronClientPlugin,
            'find_resourceid_by_name_or_id',
            side_effect=lambda x, y: y)
        self.mock_attach = self.patchobject(zun.ZunClientPlugin,
                                            'network_attach')
        self.mock_detach = self.patchobject(zun.ZunClientPlugin,
                                            'network_detach')
        self.mock_attach_check = self.patchobject(zun.ZunClientPlugin,
                                                  'check_network_attach',
                                                  return_value=True)
        self.mock_detach_check = self.patchobject(zun.ZunClientPlugin,
                                                  'check_network_detach',
                                                  return_value=True)

    def _mock_get_client(self):
        value = mock.MagicMock()
        value.name = self.fake_name
        value.image = self.fake_image
        value.command = self.fake_command
        value.cpu = self.fake_cpu
        value.memory = self.fake_memory
        value.environment = self.fake_env
        value.workdir = self.fake_workdir
        value.labels = self.fake_labels
        value.image_pull_policy = self.fake_image_policy
        value.restart_policy = self.fake_restart_policy
        value.interactive = self.fake_interactive
        value.image_driver = self.fake_image_driver
        value.hints = self.fake_hints
        value.hostname = self.fake_hostname
        value.security_groups = self.fake_security_groups
        value.addresses = self.fake_addresses
        value.to_dict.return_value = value.__dict__

        self.client.containers.get.return_value = value

    def _create_resource(self, name, snippet, stack, status='Running'):
        value = mock.MagicMock(uuid=self.resource_id)
        self.client.containers.run.return_value = value
        get_rv = mock.MagicMock(status=status)
        self.client.containers.get.return_value = get_rv
        c = container.Container(name, snippet, stack)
        return c

    def test_create(self):
        c = self._create_resource('container', self.rsrc_defn,
                                  self.stack)
        # validate the properties
        self.assertEqual(
            self.fake_name,
            c.properties.get(container.Container.NAME))
        self.assertEqual(
            self.fake_image,
            c.properties.get(container.Container.IMAGE))
        self.assertEqual(
            self.fake_command,
            c.properties.get(container.Container.COMMAND))
        self.assertEqual(
            self.fake_cpu,
            c.properties.get(container.Container.CPU))
        self.assertEqual(
            self.fake_memory,
            c.properties.get(container.Container.MEMORY))
        self.assertEqual(
            self.fake_env,
            c.properties.get(container.Container.ENVIRONMENT))
        self.assertEqual(
            self.fake_workdir,
            c.properties.get(container.Container.WORKDIR))
        self.assertEqual(
            self.fake_labels,
            c.properties.get(container.Container.LABELS))
        self.assertEqual(
            self.fake_image_policy,
            c.properties.get(container.Container.IMAGE_PULL_POLICY))
        self.assertEqual(
            'on-failure:2',
            c.properties.get(container.Container.RESTART_POLICY))
        self.assertEqual(
            self.fake_interactive,
            c.properties.get(container.Container.INTERACTIVE))
        self.assertEqual(
            self.fake_image_driver,
            c.properties.get(container.Container.IMAGE_DRIVER))
        self.assertEqual(
            self.fake_hints,
            c.properties.get(container.Container.HINTS))
        self.assertEqual(
            self.fake_hostname,
            c.properties.get(container.Container.HOSTNAME))
        self.assertEqual(
            self.fake_security_groups,
            c.properties.get(container.Container.SECURITY_GROUPS))
        self.assertEqual(
            self.fake_mounts,
            c.properties.get(container.Container.MOUNTS))
        self.assertEqual(
            self.fake_networks,
            c.properties.get(container.Container.NETWORKS))

        scheduler.TaskRunner(c.create)()
        self.assertEqual(self.resource_id, c.resource_id)
        self.assertEqual((c.CREATE, c.COMPLETE), c.state)
        self.assertEqual('containers', c.entity)
        self.client.containers.run.assert_called_once_with(
            name=self.fake_name,
            image=self.fake_image,
            command=self.fake_command,
            cpu=self.fake_cpu,
            memory=self.fake_memory,
            environment=self.fake_env,
            workdir=self.fake_workdir,
            labels=self.fake_labels,
            image_pull_policy=self.fake_image_policy,
            restart_policy=self.fake_restart_policy,
            interactive=self.fake_interactive,
            image_driver=self.fake_image_driver,
            hints=self.fake_hints,
            hostname=self.fake_hostname,
            security_groups=self.fake_security_groups,
            mounts=self.fake_mounts_args,
            nets=self.fake_networks_args,
        )

    def test_container_create_failed(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        c = self._create_resource('container', self.rsrc_defn, self.stack,
                                  status='Error')
        exc = self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(c.create))
        self.assertEqual((c.CREATE, c.FAILED), c.state)
        self.assertIn("Error in creating container ", six.text_type(exc))

    def test_container_create_unknown_status(self):
        c = self._create_resource('container', self.rsrc_defn, self.stack,
                                  status='FOO')
        exc = self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(c.create))
        self.assertEqual((c.CREATE, c.FAILED), c.state)
        self.assertIn("Unknown status Container", six.text_type(exc))

    def test_container_update(self):
        c = self._create_resource('container', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(c.create)()
        t = template_format.parse(zun_template)
        new_t = copy.deepcopy(t)
        new_t['resources'][self.fake_name]['properties']['name'] = \
            'fake-container'
        new_t['resources'][self.fake_name]['properties']['cpu'] = 10
        new_t['resources'][self.fake_name]['properties']['memory'] = 10
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_c = rsrc_defns[self.fake_name]
        scheduler.TaskRunner(c.update, new_c)()
        self.mock_update.assert_called_once_with(
            self.resource_id,
            cpu=10, memory=10, name='fake-container')
        self.assertEqual((c.UPDATE, c.COMPLETE), c.state)

    def _test_container_update_None_networks(self, new_networks):
        t = template_format.parse(zun_template_minimum)
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc_defn = resource_defns[self.fake_name]
        c = self._create_resource('container', rsrc_defn, stack)
        scheduler.TaskRunner(c.create)()

        new_t = copy.deepcopy(t)
        new_t['resources'][self.fake_name]['properties']['networks'] = \
            new_networks
        rsrc_defns = template.Template(new_t).resource_definitions(stack)
        new_c = rsrc_defns[self.fake_name]
        iface = create_fake_iface(
            port='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            net='450abbc9-9b6d-4d6f-8c3a-c47ac34100ef',
            ip='1.2.3.4')
        self.client.containers.network_list.return_value = [iface]
        scheduler.TaskRunner(c.update, new_c)()
        self.assertEqual((c.UPDATE, c.COMPLETE), c.state)
        self.client.containers.network_list.assert_called_once_with(
            self.resource_id)

    def test_container_update_None_networks_with_port(self):
        new_networks = [{'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]
        self._test_container_update_None_networks(new_networks)
        self.assertEqual(1, self.mock_attach.call_count)
        self.assertEqual(1, self.mock_detach.call_count)
        self.assertEqual(1, self.mock_attach_check.call_count)
        self.assertEqual(1, self.mock_detach_check.call_count)

    def test_container_update_None_networks_with_network_id(self):
        new_networks = [{'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                         'fixed_ip': '1.2.3.4'}]
        self._test_container_update_None_networks(new_networks)
        self.assertEqual(1, self.mock_attach.call_count)
        self.assertEqual(1, self.mock_detach.call_count)
        self.assertEqual(1, self.mock_attach_check.call_count)
        self.assertEqual(1, self.mock_detach_check.call_count)

    def test_container_update_None_networks_with_complex_parameters(self):
        new_networks = [{'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                         'fixed_ip': '1.2.3.4',
                         'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]
        self._test_container_update_None_networks(new_networks)
        self.assertEqual(1, self.mock_attach.call_count)
        self.assertEqual(1, self.mock_detach.call_count)
        self.assertEqual(1, self.mock_attach_check.call_count)
        self.assertEqual(1, self.mock_detach_check.call_count)

    def test_server_update_empty_networks_to_None(self):
        new_networks = None
        self._test_container_update_None_networks(new_networks)
        self.assertEqual(0, self.mock_attach.call_count)
        self.assertEqual(0, self.mock_detach.call_count)
        self.assertEqual(0, self.mock_attach_check.call_count)
        self.assertEqual(0, self.mock_detach_check.call_count)

    def _test_container_update_networks(self, new_networks):
        c = self._create_resource('container', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(c.create)()
        t = template_format.parse(zun_template)
        new_t = copy.deepcopy(t)
        new_t['resources'][self.fake_name]['properties']['networks'] = \
            new_networks
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_c = rsrc_defns[self.fake_name]
        sec_uuids = ['86c0f8ae-23a8-464f-8603-c54113ef5467']
        self.patchobject(neutron.NeutronClientPlugin,
                         'get_secgroup_uuids', return_value=sec_uuids)
        ifaces = [
            create_fake_iface(port='95e25541-d26a-478d-8f36-ae1c8f6b74dc',
                              net='mynet',
                              ip='10.0.0.4'),
            create_fake_iface(port='450abbc9-9b6d-4d6f-8c3a-c47ac34100ef',
                              net='mynet2',
                              ip='fe80::3'),
            create_fake_iface(port='myport',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='21.22.23.24')]
        self.client.containers.network_list.return_value = ifaces
        scheduler.TaskRunner(c.update, new_c)()
        self.assertEqual((c.UPDATE, c.COMPLETE), c.state)
        self.client.containers.network_list.assert_called_once_with(
            self.resource_id)

    def test_container_update_networks_with_complex_parameters(self):
        new_networks = [
            {'network': 'mynet',
             'fixed_ip': '10.0.0.4'},
            {'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]
        self._test_container_update_networks(new_networks)
        self.assertEqual(2, self.mock_detach.call_count)
        self.assertEqual(1, self.mock_attach.call_count)
        self.assertEqual(2, self.mock_detach_check.call_count)
        self.assertEqual(1, self.mock_attach_check.call_count)

    def test_container_update_networks_with_None(self):
        new_networks = None
        self._test_container_update_networks(new_networks)
        self.assertEqual(3, self.mock_detach.call_count)
        self.assertEqual(1, self.mock_attach.call_count)
        self.assertEqual(3, self.mock_detach_check.call_count)
        self.assertEqual(1, self.mock_attach_check.call_count)

    def test_container_update_old_networks_to_empty_list(self):
        new_networks = []
        self._test_container_update_networks(new_networks)
        self.assertEqual(3, self.mock_detach.call_count)
        self.assertEqual(1, self.mock_attach.call_count)
        self.assertEqual(3, self.mock_detach_check.call_count)
        self.assertEqual(1, self.mock_attach_check.call_count)

    def test_container_update_remove_network_non_empty(self):
        new_networks = [
            {'network': 'mynet',
             'fixed_ip': '10.0.0.4'},
            {'port': 'myport'}]
        self._test_container_update_networks(new_networks)
        self.assertEqual(1, self.mock_detach.call_count)
        self.assertEqual(0, self.mock_attach.call_count)
        self.assertEqual(1, self.mock_detach_check.call_count)
        self.assertEqual(0, self.mock_attach_check.call_count)

    def test_container_delete(self):
        c = self._create_resource('container', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(c.create)()
        self.patchobject(self.client.containers, 'get',
                         side_effect=[c, zc_exc.NotFound('Not Found')])
        scheduler.TaskRunner(c.delete)()
        self.assertEqual((c.DELETE, c.COMPLETE), c.state)
        self.client.containers.delete.assert_called_once_with(
            c.resource_id, stop=True)

    def test_container_delete_not_found(self):
        c = self._create_resource('container', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(c.create)()
        c.client_plugin = mock.MagicMock()
        self.client.containers.delete.side_effect = Exception('Not Found')
        scheduler.TaskRunner(c.delete)()
        self.assertEqual((c.DELETE, c.COMPLETE), c.state)
        self.client.containers.delete.assert_called_once_with(
            c.resource_id, stop=True)
        mock_ignore_not_found = c.client_plugin.return_value.ignore_not_found
        self.assertEqual(1, mock_ignore_not_found.call_count)

    def test_container_get_live_state(self):
        c = self._create_resource('container', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(c.create)()
        self._mock_get_client()
        reality = c.get_live_state(c.properties)
        self.assertEqual(
            {
                container.Container.NAME: self.fake_name,
                container.Container.CPU: self.fake_cpu,
                container.Container.MEMORY: self.fake_memory,
            }, reality)

    def test_resolve_attributes(self):
        self.neutron_client.list_networks.return_value = \
            self.fake_networks_attr
        c = self._create_resource('container', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(c.create)()
        self._mock_get_client()
        self.assertEqual(
            self.fake_name,
            c._resolve_attribute(container.Container.NAME))
        self.assertEqual(
            self.fake_extended_addresses,
            c._resolve_attribute(container.Container.ADDRESSES))

    def test_resolve_attributes_duplicate_net_name(self):
        self.neutron_client.list_networks.return_value = {
            'networks': [
                {'id': 'fake_net_id', 'name': 'test'},
                {'id': 'fake_net_id2', 'name': 'test'},
            ]
        }
        self.fake_addresses = {
            'fake_net_id': [{'addr': '10.0.0.12'}],
            'fake_net_id2': [{'addr': '10.100.0.12'}],
        }
        self.fake_extended_addresses = {
            'fake_net_id': [{'addr': '10.0.0.12'}],
            'fake_net_id2': [{'addr': '10.100.0.12'}],
            'test': [{'addr': '10.0.0.12'}, {'addr': '10.100.0.12'}],
        }
        c = self._create_resource('container', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(c.create)()
        self._mock_get_client()
        self._assert_addresses(
            self.fake_extended_addresses,
            c._resolve_attribute(container.Container.ADDRESSES))

    def _assert_addresses(self, expected, actual):
        matched = True
        if len(expected) != len(actual):
            matched = False
        for key in expected:
            if key not in actual:
                matched = False
                break
            list1 = expected[key]
            list1 = sorted(list1, key=lambda x: sorted(x.values()))
            list2 = actual[key]
            list2 = sorted(list2, key=lambda x: sorted(x.values()))
            if list1 != list2:
                matched = False
                break

        if not matched:
            raise AssertionError(
                'Addresses is unmatched:\n reference = ' + str(expected) +
                '\nactual = ' + str(actual))
