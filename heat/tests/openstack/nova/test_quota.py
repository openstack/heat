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
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import keystone as k_plugin
from heat.engine.clients.os import nova as n_plugin
from heat.engine import rsrc_defn
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils

quota_template = '''
heat_template_version: newton

description: Sample nova quota heat template

resources:
  my_quota:
    type: OS::Nova::Quota
    properties:
      project: demo
      cores: 5
      fixed_ips: 5
      floating_ips: 5
      instances: 5
      injected_files: 5
      injected_file_content_bytes: 5
      injected_file_path_bytes: 5
      key_pairs: 5
      metadata_items: 5
      ram: 5
      security_groups: 5
      security_group_rules: 5
      server_groups: 5
      server_group_members: 5
'''

valid_properties = [
    'cores', 'fixed_ips', 'floating_ips', 'instances', 'injected_files',
    'injected_file_content_bytes', 'injected_file_path_bytes', 'key_pairs',
    'metadata_items', 'ram', 'security_groups', 'security_group_rules',
    'server_groups', 'server_group_members'
]


class NovaQuotaTest(common.HeatTestCase):
    def setUp(self):
        super(NovaQuotaTest, self).setUp()

        self.ctx = utils.dummy_context()
        self.patchobject(n_plugin.NovaClientPlugin, 'has_extension',
                         return_value=True)
        self.patchobject(k_plugin.KeystoneClientPlugin, 'get_project_id',
                         return_value='some_project_id')
        tpl = template_format.parse(quota_template)
        self.stack = parser.Stack(
            self.ctx, 'nova_quota_test_stack',
            template.Template(tpl)
        )

        self.my_quota = self.stack['my_quota']
        nova = mock.MagicMock()
        self.novaclient = mock.MagicMock()
        self.my_quota.client = nova
        nova.return_value = self.novaclient
        self.quotas = self.novaclient.quotas
        self.quota_set = mock.MagicMock()
        self.quotas.update.return_value = self.quota_set
        self.quotas.delete.return_value = self.quota_set

    def _test_validate(self, resource, error_msg):
        exc = self.assertRaises(exception.StackValidationFailed,
                                resource.validate)
        self.assertIn(error_msg, six.text_type(exc))

    def _test_invalid_property(self, prop_name):
        my_quota = self.stack['my_quota']
        props = self.stack.t.t['resources']['my_quota']['properties'].copy()
        props[prop_name] = -2
        my_quota.t = my_quota.t.freeze(properties=props)
        my_quota.reparse()
        error_msg = ('Property error: resources.my_quota.properties.%s:'
                     ' -2 is out of range (min: -1, max: None)' % prop_name)
        self._test_validate(my_quota, error_msg)

    def test_invalid_properties(self):
        for prop in valid_properties:
            self._test_invalid_property(prop)

    def test_miss_all_quotas(self):
        my_quota = self.stack['my_quota']
        props = self.stack.t.t['resources']['my_quota']['properties'].copy()
        for key in valid_properties:
            if key in props:
                del props[key]
        my_quota.t = my_quota.t.freeze(properties=props)
        my_quota.reparse()
        msg = ('At least one of the following properties must be specified: '
               'cores, fixed_ips, floating_ips, injected_file_content_bytes, '
               'injected_file_path_bytes, injected_files, instances, '
               'key_pairs, metadata_items, ram, security_group_rules, '
               'security_groups, server_group_members, server_groups.')
        self.assertRaisesRegex(exception.PropertyUnspecifiedError, msg,
                               my_quota.validate)

    def test_quota_handle_create(self):
        self.my_quota.physical_resource_name = mock.MagicMock(
            return_value='some_resource_id')
        self.my_quota.reparse()
        self.my_quota.handle_create()
        self.quotas.update.assert_called_once_with(
            'some_project_id',
            cores=5,
            fixed_ips=5,
            floating_ips=5,
            instances=5,
            injected_files=5,
            injected_file_content_bytes=5,
            injected_file_path_bytes=5,
            key_pairs=5,
            metadata_items=5,
            ram=5,
            security_groups=5,
            security_group_rules=5,
            server_groups=5,
            server_group_members=5
        )
        self.assertEqual('some_resource_id', self.my_quota.resource_id)

    def test_quota_handle_update(self):
        tmpl_diff = mock.MagicMock()
        prop_diff = mock.MagicMock()
        props = {'project': 'some_project_id', 'cores': 1, 'fixed_ips': 2,
                 'instances': 3, 'injected_file_content_bytes': 4, 'ram': 200}
        json_snippet = rsrc_defn.ResourceDefinition(
            self.my_quota.name,
            'OS::Nova::Quota',
            properties=props)
        self.my_quota.reparse()
        self.my_quota.handle_update(json_snippet, tmpl_diff, prop_diff)
        self.quotas.update.assert_called_once_with(
            'some_project_id',
            cores=1,
            fixed_ips=2,
            instances=3,
            injected_file_content_bytes=4,
            ram=200
        )

    def test_quota_handle_delete(self):
        self.my_quota.reparse()
        self.my_quota.handle_delete()
        self.quotas.delete.assert_called_once_with('some_project_id')
