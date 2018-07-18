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

from blazarclient import exception as client_exception
import mock
from oslo_utils.fixture import uuidsentinel as uuids

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import blazar
from heat.engine.resources.openstack.blazar import host
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


blazar_host_template = '''
heat_template_version: rocky

resources:
  test-host:
    type: OS::Blazar::Host
    properties:
      name: test-host
      extra_capability:
        gpu: true
'''

blazar_host_template_extra_capability = '''
heat_template_version: rocky

resources:
  test-host:
    type: OS::Blazar::Host
    properties:
      name: test-host
      extra_capability:
        gpu: true
        name: test-name
'''


class BlazarHostTestCase(common.HeatTestCase):

    def setUp(self):
        super(BlazarHostTestCase, self).setUp()

        self.host = {
            "id": uuids.id,
            "name": "test-host",
            "gpu": True,
            "hypervisor_hostname": "compute-1",
            "hypervisor_type": "QEMU",
            "hypervisor_version": 2010001,
            "cpu_info": "{"
                        "'arch': 'x86_64', 'model': 'cpu64-rhel6', "
                        "'vendor': 'Intel', 'features': "
                        "['pge', 'clflush', 'sep', 'syscall', 'msr', "
                        "'vmx', 'cmov', 'nx', 'pat', 'lm', 'tsc', "
                        "'fpu', 'fxsr', 'pae', 'mmx', 'cx8', 'mce', "
                        "'de', 'mca', 'pse', 'pni', 'apic', 'sse', "
                        "'lahf_lm', 'sse2', 'hypervisor', 'cx16', "
                        "'pse36', 'mttr', 'x2apic'], "
                        "'topology': {'cores': 1, 'cells': 1, 'threads': 1, "
                        "'sockets': 4}}",
            "memory_mb": 8192,
            "local_gb": 100,
            "vcpus": 2,
            "service_name": "compute-1",
            "reservable": True,
            "trust_id": uuids.trust_id,
            "created_at": "2020-01-01 08:00",
            "updated_at": "2020-01-01 12:00",
            "extra_capability": "foo"
        }
        t = template_format.parse(blazar_host_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['test-host']
        self.client = mock.Mock()
        self.patchobject(blazar.BlazarClientPlugin, 'client',
                         return_value=self.client)

    def _create_resource(self, name, snippet, stack):
        self.client.host.create.return_value = self.host
        return host.Host(name, snippet, stack)

    def test_host_create(self):
        host_resource = self._create_resource('host', self.rsrc_defn,
                                              self.stack)

        self.assertEqual(self.host['name'],
                         host_resource.properties.get(host.Host.NAME))

        scheduler.TaskRunner(host_resource.create)()
        self.assertEqual(uuids.id, host_resource.resource_id)
        self.assertEqual((host_resource.CREATE, host_resource.COMPLETE),
                         host_resource.state)
        self.assertEqual('host', host_resource.entity)
        self.client.host.create.assert_called_once_with(
            name=self.host['name'], gpu=self.host['gpu'])

    def test_host_delete(self):
        host_resource = self._create_resource('host', self.rsrc_defn,
                                              self.stack)

        scheduler.TaskRunner(host_resource.create)()
        self.client.host.delete.return_value = None
        self.client.host.get.side_effect = [
            'host_obj', client_exception.BlazarClientException(code=404)]
        scheduler.TaskRunner(host_resource.delete)()
        self.assertEqual((host_resource.DELETE, host_resource.COMPLETE),
                         host_resource.state)
        self.client.host.delete.assert_called_once_with(uuids.id)

    def test_host_delete_not_found(self):
        host_resource = self._create_resource('host', self.rsrc_defn,
                                              self.stack)

        scheduler.TaskRunner(host_resource.create)()
        self.client.host.delete.side_effect = client_exception.\
            BlazarClientException(code=404)
        self.client.host.get.side_effect = client_exception.\
            BlazarClientException(code=404)
        scheduler.TaskRunner(host_resource.delete)()
        self.assertEqual((host_resource.DELETE, host_resource.COMPLETE),
                         host_resource.state)

    def test_parse_extra_capability(self):
        t = template_format.parse(blazar_host_template_extra_capability)
        stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(stack)
        rsrc_defn = resource_defns['test-host']
        host_resource = self._create_resource('host', rsrc_defn, stack)
        args = dict((k, v) for k, v in host_resource.properties.items()
                    if v is not None)
        parsed_args = host_resource._parse_extra_capability(args)
        self.assertEqual({'gpu': True, 'name': 'test-host'}, parsed_args)

    def test_resolve_attributes(self):
        host_resource = self._create_resource('host', self.rsrc_defn,
                                              self.stack)

        scheduler.TaskRunner(host_resource.create)()
        self.client.host.get.return_value = self.host
        self.assertEqual(self.host['vcpus'],
                         host_resource._resolve_attribute(host.Host.VCPUS))

    def test_resolve_attributes_not_found(self):
        host_resource = self._create_resource('host', self.rsrc_defn,
                                              self.stack)

        scheduler.TaskRunner(host_resource.create)()
        self.client.host.get.return_value = self.host
        self.assertRaises(exception.InvalidTemplateAttribute,
                          host_resource._resolve_attribute,
                          'invalid_attribute')
