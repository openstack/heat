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
from heat.engine.resources.openstack.blazar import lease
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


blazar_lease_host_template = '''
heat_template_version: rocky

resources:
  test-lease:
    type: OS::Blazar::Lease
    properties:
     name: test-lease
     start_date: '2020-01-01 09:00'
     end_date: '2020-01-10 17:30'
     reservations:
        - resource_type: 'physical:host'
          min: 1
          max: 1
          hypervisor_properties: '[">=", "$vcpus", "2"]'
          resource_properties: ''
          before_end: 'default'
'''

blazar_lease_instance_template = '''
heat_template_version: rocky

resources:
  test-lease:
    type: OS::Blazar::Lease
    properties:
      name: test-lease
      start_date: '2020-01-01 09:00'
      end_date: '2020-01-10 17:30'
      reservations:
        - resource_type: 'virtual:instance'
          amount: 1
          vcpus: 1
          memory_mb: 512
          disk_gb: 15
          affinity: false
          resource_properties: ''
'''


class BlazarLeaseTestCase(common.HeatTestCase):

    def setUp(self):
        super(BlazarLeaseTestCase, self).setUp()

        self.lease = {
            "id": uuids.lease_id,
            "name": "test-lease",
            "start_date": "2020-01-01 09:00",
            "end_date": "2020-01-10 17:30",
            "created_at": "2020-01-01 08:00",
            "updated_at": "2020-01-01 12:00",
            "degraded": False,
            "user_id": uuids.user_id,
            "project_id": uuids.project_id,
            "trust_id": uuids.trust_id,
            "reservations": [
                {
                    "resource_type": "physical:host",
                    "min": 1,
                    "max": 1,
                    "hypervisor_properties": "[\">=\", \"$vcpus\", \"2\"]",
                    "resource_properties": "",
                    "before_end": "default"
                },
            ],
            "events": []
        }

        t = template_format.parse(blazar_lease_host_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['test-lease']
        self.client = mock.Mock()
        self.patchobject(blazar.BlazarClientPlugin, 'client',
                         return_value=self.client)

    def _create_resource(self, name, snippet, stack):
        self.client.lease.create.return_value = self.lease
        return lease.Lease(name, snippet, stack)

    def test_lease_host_create(self):
        self.patchobject(blazar.BlazarClientPlugin, 'client',
                         return_value=self.client)
        self.client.has_host.return_value = True
        lease_resource = self._create_resource('lease', self.rsrc_defn,
                                               self.stack)
        self.assertEqual(self.lease['name'],
                         lease_resource.properties.get(lease.Lease.NAME))

        self.assertIsNone(lease_resource.validate())

        scheduler.TaskRunner(lease_resource.create)()
        self.assertEqual(uuids.lease_id,
                         lease_resource.resource_id)
        self.assertEqual((lease_resource.CREATE, lease_resource.COMPLETE),
                         lease_resource.state)
        self.assertEqual('lease', lease_resource.entity)
        self.client.lease.create.assert_called_once_with(
            name=self.lease['name'], start=self.lease['start_date'],
            end=self.lease['end_date'],
            reservations=self.lease['reservations'],
            events=self.lease['events'])

    def test_lease_host_create_validate_fail(self):
        self.patchobject(lease.Lease, 'client_plugin',
                         return_value=self.client)
        self.client.has_host.return_value = False
        lease_resource = self._create_resource('lease', self.rsrc_defn,
                                               self.stack)
        self.assertEqual(self.lease['name'],
                         lease_resource.properties.get(lease.Lease.NAME))

        self.assertRaises(exception.StackValidationFailed,
                          lease_resource.validate)

    def test_lease_instance_create(self):
        t = template_format.parse(blazar_lease_instance_template)
        stack = utils.parse_stack(t)
        resource_defn = stack.t.resource_definitions(stack)
        rsrc_defn = resource_defn['test-lease']

        lease_resource = self._create_resource('lease', rsrc_defn, stack)

        self.assertEqual(self.lease['name'],
                         lease_resource.properties.get(lease.Lease.NAME))

        scheduler.TaskRunner(lease_resource.create)()
        self.assertEqual(uuids.lease_id,
                         lease_resource.resource_id)
        self.assertEqual((lease_resource.CREATE,
                          lease_resource.COMPLETE), lease_resource.state)
        self.assertEqual('lease', lease_resource.entity)

        reservations = [
            {
                'resource_type': 'virtual:instance',
                'amount': 1,
                'vcpus': 1,
                'memory_mb': 512,
                'disk_gb': 15,
                'affinity': False,
                'resource_properties': ''
            }
        ]

        self.client.lease.create.assert_called_once_with(
            name=self.lease['name'], start=self.lease['start_date'],
            end=self.lease['end_date'],
            reservations=reservations,
            events=self.lease['events'])

    def test_lease_delete(self):
        lease_resource = self._create_resource('lease', self.rsrc_defn,
                                               self.stack)
        self.client.lease.delete.return_value = None

        scheduler.TaskRunner(lease_resource.create)()
        self.client.lease.get.side_effect = [
            'lease_obj', client_exception.BlazarClientException(code=404)]
        scheduler.TaskRunner(lease_resource.delete)()
        self.assertEqual((lease_resource.DELETE, lease_resource.COMPLETE),
                         lease_resource.state)
        self.assertEqual(1, self.client.lease.delete.call_count)

    def test_lease_delete_not_found(self):
        lease_resource = self._create_resource('lease', self.rsrc_defn,
                                               self.stack)

        scheduler.TaskRunner(lease_resource.create)()
        self.client.lease.delete.side_effect = client_exception.\
            BlazarClientException(code=404)
        self.client.lease.get.side_effect = client_exception.\
            BlazarClientException(code=404)
        scheduler.TaskRunner(lease_resource.delete)()
        self.assertEqual((lease_resource.DELETE, lease_resource.COMPLETE),
                         lease_resource.state)

    def test_resolve_attributes(self):
        lease_resource = self._create_resource('lease', self.rsrc_defn,
                                               self.stack)

        scheduler.TaskRunner(lease_resource.create)()
        self.client.lease.get.return_value = self.lease
        self.assertEqual(self.lease['start_date'],
                         lease_resource._resolve_attribute
                         (lease.Lease.START_DATE))

    def test_resolve_attributes_not_found(self):
        lease_resource = self._create_resource('lease', self.rsrc_defn,
                                               self.stack)

        scheduler.TaskRunner(lease_resource.create)()
        self.client.lease.get.return_value = self.lease
        self.assertRaises(exception.InvalidTemplateAttribute,
                          lease_resource._resolve_attribute,
                          "invalid_attribute")
