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
from oslo_config import cfg
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import magnum as mc
from heat.engine import resource
from heat.engine.resources.openstack.magnum import bay
from heat.engine import scheduler
from heat.engine import template
from heat.tests import common
from heat.tests import utils


magnum_template = '''
    heat_template_version: 2015-04-30
    resources:
      test_bay:
        type: OS::Magnum::Bay
        properties:
          name: test_bay
          baymodel: 123456
          node_count: 5
          master_count: 1
          discovery_url: https://discovery.etcd.io
          bay_create_timeout: 15
'''

RESOURCE_TYPE = 'OS::Magnum::Bay'


class TestMagnumBay(common.HeatTestCase):
    def setUp(self):
        super(TestMagnumBay, self).setUp()
        resource._register_class(RESOURCE_TYPE, bay.Bay)
        t = template_format.parse(magnum_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['test_bay']
        self.client = mock.Mock()
        self.patchobject(bay.Bay, 'client', return_value=self.client)
        self.patchobject(mc.MagnumClientPlugin, 'get_baymodel')

    def _create_resource(self, name, snippet, stack, stat='CREATE_COMPLETE'):
        self.resource_id = '12345'
        value = mock.MagicMock(uuid=self.resource_id)
        self.client.bays.create.return_value = value
        get_rv = mock.MagicMock(status=stat)
        self.client.bays.get.return_value = get_rv
        b = bay.Bay(name, snippet, stack)
        return b

    def test_bay_create(self):
        b = self._create_resource('bay', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(b.create)()
        self.assertEqual(self.resource_id, b.resource_id)
        self.assertEqual((b.CREATE, b.COMPLETE), b.state)

    def test_bay_create_failed(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        b = self._create_resource('bay', self.rsrc_defn, self.stack,
                                  stat='CREATE_FAILED')
        exc = self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(b.create))
        self.assertIn("Failed to create Bay", six.text_type(exc))

    def test_bay_create_unknown_status(self):
        b = self._create_resource('bay', self.rsrc_defn, self.stack,
                                  stat='CREATE_FOO')
        exc = self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(b.create))
        self.assertIn("Unknown status creating Bay", six.text_type(exc))

    def test_bay_update(self):
        b = self._create_resource('bay', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(b.create)()
        status = mock.MagicMock(status='UPDATE_COMPLETE')
        self.client.bays.get.return_value = status
        t = template_format.parse(magnum_template)
        new_t = copy.deepcopy(t)
        new_t['resources']['test_bay']['properties']['node_count'] = 10
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_bm = rsrc_defns['test_bay']
        scheduler.TaskRunner(b.update, new_bm)()
        self.assertEqual((b.UPDATE, b.COMPLETE), b.state)

    def test_bay_update_failed(self):
        b = self._create_resource('bay', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(b.create)()
        status = mock.MagicMock(status='UPDATE_FAILED')
        self.client.bays.get.return_value = status
        t = template_format.parse(magnum_template)
        new_t = copy.deepcopy(t)
        new_t['resources']['test_bay']['properties']['node_count'] = 10
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_bm = rsrc_defns['test_bay']
        exc = self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(b.update, new_bm))
        self.assertIn("Failed to update Bay", six.text_type(exc))

    def test_bay_update_unknown_status(self):
        b = self._create_resource('bay', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(b.create)()
        status = mock.MagicMock(status='UPDATE_BAR')
        self.client.bays.get.return_value = status
        t = template_format.parse(magnum_template)
        new_t = copy.deepcopy(t)
        new_t['resources']['test_bay']['properties']['node_count'] = 10
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_bm = rsrc_defns['test_bay']
        exc = self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(b.update, new_bm))
        self.assertIn("Unknown status updating Bay", six.text_type(exc))

    def test_bay_delete(self):
        b = self._create_resource('bay', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(b.create)()
        b.client_plugin = mock.MagicMock()
        self.client.bays.get.side_effect = Exception('Not Found')
        self.client.get.reset_mock()
        scheduler.TaskRunner(b.delete)()
        self.assertEqual((b.DELETE, b.COMPLETE), b.state)
        self.assertEqual(2, self.client.bays.get.call_count)

    def test_bay_get_live_state(self):
        b = self._create_resource('bay', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(b.create)()
        value = mock.MagicMock()
        value.to_dict.return_value = {
            'name': 'test_bay',
            'baymodel': 123456,
            'node_count': 5,
            'master_count': 1,
            'discovery_url': 'https://discovery.etcd.io',
            'bay_create_timeout': 15}
        self.client.bays.get.return_value = value
        reality = b.get_live_state(b.properties)
        self.assertEqual({'node_count': 5, 'master_count': 1}, reality)
