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

from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine import resource
from heat.engine.resources.openstack.keystone import domain
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

KEYSTONE_REGION_TEMPLATE = {
    'heat_template_version': '2017-02-24',
    'resources': {
        'test_domain': {
            'type': 'OS::Keystone::Domain',
            'properties': {
                'name': 'test_domain_1',
                'description': 'Test domain',
                'enabled': 'True'
            }
        }
    }
}


class KeystoneDomainTest(common.HeatTestCase):
    def setUp(self):
        super(KeystoneDomainTest, self).setUp()

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack_keystone',
            template.Template(KEYSTONE_REGION_TEMPLATE)
        )

        self.test_domain = self.stack['test_domain']

        # Mock client
        self.keystoneclient = mock.Mock()
        self.patchobject(resource.Resource, 'client',
                         return_value=fake_ks.FakeKeystoneClient(
                             client=self.keystoneclient))
        self.domains = self.keystoneclient.domains

        keystone_client_plugin = mock.MagicMock()
        self.test_domain.client_plugin = mock.MagicMock()
        self.test_domain.client_plugin.return_value = keystone_client_plugin

    def _get_mock_domain(self):
        value = mock.MagicMock()
        domain_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        value.id = domain_id

        return value

    def test_domain_handle_create(self):
        mock_domain = self._get_mock_domain()
        self.domains.create.return_value = mock_domain

        # validate the properties
        self.assertEqual(
            'test_domain_1',
            self.test_domain.properties.get(domain.KeystoneDomain.NAME))
        self.assertEqual(
            'Test domain',
            self.test_domain.properties.get(
                domain.KeystoneDomain.DESCRIPTION))
        self.assertEqual(
            True,
            self.test_domain.properties.get(domain.KeystoneDomain.ENABLED))

        self.test_domain.handle_create()

        # validate domain creation
        self.domains.create.assert_called_once_with(
            name='test_domain_1',
            description='Test domain',
            enabled=True)

        # validate physical resource id
        self.assertEqual(mock_domain.id, self.test_domain.resource_id)

    def test_domain_handle_update(self):
        self.test_domain.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {domain.KeystoneDomain.DESCRIPTION:
                     'Test Domain updated',
                     domain.KeystoneDomain.ENABLED: False,
                     domain.KeystoneDomain.NAME: 'test_domain_2'}

        self.test_domain.handle_update(json_snippet=None,
                                       tmpl_diff=None,
                                       prop_diff=prop_diff)

        self.domains.update.assert_called_once_with(
            domain=self.test_domain.resource_id,
            description=prop_diff[domain.KeystoneDomain.DESCRIPTION],
            enabled=prop_diff[domain.KeystoneDomain.ENABLED],
            name='test_domain_2'
        )

    def test_get_live_state(self):
        sample_domain = {
            domain.KeystoneDomain.NAME: 'test',
            domain.KeystoneDomain.ENABLED: True,
            domain.KeystoneDomain.DESCRIPTION: 'test domain'
        }
        d = mock.Mock()
        d.to_dict.return_value = sample_domain
        self.domains.get.return_value = d

        reality = self.test_domain.get_live_state(self.test_domain.properties)
        self.assertEqual(sample_domain, reality)
