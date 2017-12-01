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

from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine import resource
from heat.engine.resources.openstack.keystone import role
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

keystone_role_template = {
    'heat_template_version': '2013-05-23',
    'resources': {
        'test_role': {
            'type': 'OS::Keystone::Role',
            'properties': {
                'name': 'test_role_1'
            }
        }
    }
}


class KeystoneRoleTest(common.HeatTestCase):
    def setUp(self):
        super(KeystoneRoleTest, self).setUp()

        self.ctx = utils.dummy_context()
        # Mock client
        self.keystoneclient = mock.Mock()
        self.patchobject(resource.Resource, 'client',
                         return_value=fake_ks.FakeKeystoneClient(
                             client=self.keystoneclient))
        self.roles = self.keystoneclient.roles

    def _get_rsrc(self, domain='default', without_name=False):
        t = template.Template(keystone_role_template)
        tmpl = copy.deepcopy(t)
        tmpl['resources']['test_role']['Properties']['domain'] = domain
        if without_name:
            tmpl['resources']['test_role']['Properties'].pop('name')
        test_stack = stack.Stack(self.ctx, 'test_keystone_role', tmpl)
        test_role = test_stack['test_role']
        return test_role

    def _get_mock_role(self, domain='default'):
        value = mock.MagicMock()
        role_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        domain_id = domain
        value.id = role_id
        value.domain_id = domain_id
        return value

    def _test_handle_create(self, domain='default'):
        test_role = self._get_rsrc(domain)
        mock_role = self._get_mock_role(domain)
        self.roles.create.return_value = mock_role

        # validate the properties
        self.assertEqual('test_role_1',
                         test_role.properties.get(role.KeystoneRole.NAME))
        self.assertEqual(domain,
                         test_role.properties.get(role.KeystoneRole.DOMAIN))

        test_role.handle_create()

        # validate role creation with given name
        self.roles.create.assert_called_once_with(name='test_role_1',
                                                  domain=domain)

        # validate physical resource id
        self.assertEqual(mock_role.id, test_role.resource_id)

    def test_role_handle_create(self):
        self._test_handle_create()

    def test_role_handle_create_with_domain(self):
        self._test_handle_create(domain='d_test')

    def test_role_handle_create_default_name(self):
        # reset the NAME value to None, to make sure role is
        # created with physical_resource_name
        test_role = self._get_rsrc(without_name=True)
        test_role.physical_resource_name = mock.Mock(
            return_value='phy_role_name')
        test_role.handle_create()

        # validate role creation with default name
        self.roles.create.assert_called_once_with(name='phy_role_name',
                                                  domain='default')

    def test_role_handle_update(self):
        test_role = self._get_rsrc()
        test_role.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        # update the name property
        prop_diff = {role.KeystoneRole.NAME: 'test_role_1_updated'}

        test_role.handle_update(json_snippet=None,
                                tmpl_diff=None,
                                prop_diff=prop_diff)

        self.roles.update.assert_called_once_with(
            role=test_role.resource_id,
            name=prop_diff[role.KeystoneRole.NAME]
        )

    def test_show_resource(self):
        role = mock.Mock()
        role.to_dict.return_value = {'attr': 'val'}
        self.roles.get.return_value = role
        test_role = self._get_rsrc()
        res = test_role._show_resource()
        self.assertEqual({'attr': 'val'}, res)
