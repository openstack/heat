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

import json
from unittest import mock

from novaclient import exceptions
from oslo_utils import excutils

from heat.common import template_format
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

sg_template = {
    "heat_template_version": "2013-05-23",
    "resources": {
        "ServerGroup": {
            "type": "OS::Nova::ServerGroup",
            "properties": {
                "name": "test",
                "policies": ["anti-affinity"],
                "rules": {
                    "max_server_per_host": 8}
            }
        }
    }
}


class FakeGroup(object):
    def __init__(self, name):
        self.id = name
        self.name = name


class NovaServerGroupTest(common.HeatTestCase):
    def setUp(self):
        super(NovaServerGroupTest, self).setUp()

    def _init_template(self, sg_template):
        template = template_format.parse(json.dumps(sg_template))
        self.stack = utils.parse_stack(template)
        self.sg = self.stack['ServerGroup']
        # create mock clients and objects
        nova = mock.MagicMock()
        self.sg.client = mock.MagicMock(return_value=nova)

        class FakeNovaPlugin(object):

            @excutils.exception_filter
            def ignore_not_found(self, ex):
                if not isinstance(ex, exceptions.NotFound):
                    raise ex

            def is_version_supported(self, version):
                return True

            def is_conflict(self, ex):
                return False

        self.patchobject(excutils.exception_filter, '__exit__')
        self.patchobject(self.sg, 'client_plugin',
                         return_value=FakeNovaPlugin())
        self.sg_mgr = nova.server_groups

    def _create_sg(self, name):
        if name:
            sg = sg_template['resources']['ServerGroup']
            sg['properties']['name'] = name
            self._init_template(sg_template)
            self.sg_mgr.create.return_value = FakeGroup(name)
        else:
            try:
                sg = sg_template['resources']['ServerGroup']
                del sg['properties']['name']
            except Exception:
                pass
            self._init_template(sg_template)
            name = 'test'
            n = name

            def fake_create(name, policy, rules):
                self.assertGreater(len(name), 1)
                return FakeGroup(n)
            self.sg_mgr.create = fake_create
        scheduler.TaskRunner(self.sg.create)()
        self.assertEqual((self.sg.CREATE, self.sg.COMPLETE),
                         self.sg.state)
        self.assertEqual(name, self.sg.resource_id)

    def test_sg_create(self):
        self._create_sg('test')
        expected_args = ()
        expected_kwargs = {'name': 'test',
                           'policy': "anti-affinity",
                           'rules': {
                               'max_server_per_host': 8}
                           }
        self.sg_mgr.create.assert_called_once_with(*expected_args,
                                                   **expected_kwargs)

    def test_sg_create_no_name(self):
        self._create_sg(None)

    def test_sg_show_resource(self):
        self._create_sg('test')
        self.sg.client = mock.MagicMock()
        s_groups = mock.MagicMock()
        sg = mock.MagicMock()
        sg.to_dict.return_value = {'server_gr': 'info'}
        s_groups.get.return_value = sg
        self.sg.client().server_groups = s_groups
        self.assertEqual({'server_gr': 'info'}, self.sg.FnGetAtt('show'))
        s_groups.get.assert_called_once_with('test')

    def test_needs_replace_failed(self):
        self._create_sg('test')
        self.sg.state_set(self.sg.CREATE, self.sg.FAILED)
        mock_show_resource = self.patchobject(self.sg, '_show_resource')
        mock_show_resource.side_effect = [exceptions.NotFound(404), None]

        self.sg.resource_id = None
        self.assertTrue(self.sg.needs_replace_failed())
        self.assertEqual(0, mock_show_resource.call_count)

        self.sg.resource_id = 'sg_id'
        self.assertTrue(self.sg.needs_replace_failed())
        self.assertEqual(1, mock_show_resource.call_count)

        mock_show_resource.return_value = None
        self.assertFalse(self.sg.needs_replace_failed())
        self.assertEqual(2, mock_show_resource.call_count)
