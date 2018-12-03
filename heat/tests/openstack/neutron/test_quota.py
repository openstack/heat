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
from heat.engine.clients.os import neutron as n_plugin
from heat.engine import rsrc_defn
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils

quota_template = '''
heat_template_version: newton

description: Sample neutron quota heat template

resources:
  my_quota:
    type: OS::Neutron::Quota
    properties:
      project: demo
      subnet: 5
      network: 5
      floatingip: 5
      security_group_rule: 5
      security_group: 5
      router: 5
      port: 5
      subnetpool: 5
      rbac_policy: 5
'''

valid_properties = [
    'subnet', 'network', 'floatingip', 'security_group_rule',
    'security_group', 'router', 'port', 'subnetpool', 'rbac_policy'
]


class NeutronQuotaTest(common.HeatTestCase):
    def setUp(self):
        super(NeutronQuotaTest, self).setUp()

        self.ctx = utils.dummy_context()
        self.patchobject(n_plugin.NeutronClientPlugin, 'has_extension',
                         return_value=True)
        self.patchobject(n_plugin.NeutronClientPlugin, 'ignore_not_found',
                         return_value=None)
        self.patchobject(k_plugin.KeystoneClientPlugin, 'get_project_id',
                         return_value='some_project_id')
        tpl = template_format.parse(quota_template)
        self.stack = parser.Stack(
            self.ctx, 'neutron_quota_test_stack',
            template.Template(tpl)
        )

        self.my_quota = self.stack['my_quota']
        neutron = mock.MagicMock()
        self.neutronclient = mock.MagicMock()
        self.my_quota.client = neutron
        neutron.return_value = self.neutronclient
        self.update_quota = self.neutronclient.update_quota
        self.delete_quota = self.neutronclient.delete_quota
        self.update_quota.return_value = mock.MagicMock()
        self.delete_quota.return_value = mock.MagicMock()

    def _test_validate(self, resource, error_msg):
        exc = self.assertRaises(exception.StackValidationFailed,
                                resource.validate)
        self.assertIn(error_msg, six.text_type(exc))

    def test_miss_all_quotas(self):
        my_quota = self.stack['my_quota']
        props = self.stack.t.t['resources']['my_quota']['properties'].copy()
        for key in valid_properties:
            if key in props:
                del props[key]
        my_quota.t = my_quota.t.freeze(properties=props)
        my_quota.reparse()

        msg = ('At least one of the following properties must be specified: '
               'floatingip, network, port, rbac_policy, router, '
               'security_group, security_group_rule, subnet, '
               'subnetpool.')
        self.assertRaisesRegex(exception.PropertyUnspecifiedError, msg,
                               my_quota.validate)

    def test_quota_handle_create(self):
        self.my_quota.physical_resource_name = mock.MagicMock(
            return_value='some_resource_id')
        self.my_quota.reparse()
        self.my_quota.handle_create()
        body = {
            "quota": {
                'subnet': 5,
                'network': 5,
                'floatingip': 5,
                'security_group_rule': 5,
                'security_group': 5,
                'router': 5,
                'port': 5,
                'subnetpool': 5,
                'rbac_policy': 5
            }
        }
        self.update_quota.assert_called_once_with(
            'some_project_id',
            body
        )
        self.assertEqual('some_resource_id', self.my_quota.resource_id)

    def test_quota_handle_update(self):
        tmpl_diff = mock.MagicMock()
        prop_diff = mock.MagicMock()
        props = {'project': 'some_project_id', 'floatingip': 1,
                 'security_group': 4, 'rbac_policy': 8}
        json_snippet = rsrc_defn.ResourceDefinition(
            self.my_quota.name,
            'OS::Neutron::Quota',
            properties=props)
        self.my_quota.reparse()
        self.my_quota.handle_update(json_snippet, tmpl_diff, prop_diff)
        body = {
            "quota": {
                'floatingip': 1,
                'security_group': 4,
                'rbac_policy': 8
            }
        }
        self.update_quota.assert_called_once_with(
            'some_project_id',
            body
        )

    def test_quota_handle_delete(self):
        self.my_quota.reparse()
        self.my_quota.resource_id_set('some_project_id')
        self.my_quota.handle_delete()
        self.delete_quota.assert_called_once_with('some_project_id')
