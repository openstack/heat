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

from designateclient import exceptions as designate_exception
from designateclient.v1 import domains

from heat.engine.resources.openstack.designate import domain
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils


sample_template = {
    'heat_template_version': '2015-04-30',
    'resources': {
        'test_resource': {
            'type': 'OS::Designate::Domain',
            'properties': {
                'name': 'test-domain.com',
                'description': 'Test domain',
                'ttl': 3600,
                'email': 'abc@test-domain.com'
            }
        }
    }
}


class DesignateDomainTest(common.HeatTestCase):

    def setUp(self):
        super(DesignateDomainTest, self).setUp()

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack',
            template.Template(sample_template)
        )

        self.test_resource = self.stack['test_resource']

        # Mock client plugin
        self.test_client_plugin = mock.MagicMock()
        self.test_resource.client_plugin = mock.MagicMock(
            return_value=self.test_client_plugin)

        # Mock client
        self.test_client = mock.MagicMock()
        self.test_resource.client = mock.MagicMock(
            return_value=self.test_client)

    def _get_mock_resource(self):
        value = mock.MagicMock()
        value.id = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
        value.serial = '1434596972'

        return value

    def test_resource_handle_create(self):
        mock_domain_create = self.test_client_plugin.domain_create
        mock_resource = self._get_mock_resource()
        mock_domain_create.return_value = mock_resource

        # validate the properties
        self.assertEqual(
            'test-domain.com',
            self.test_resource.properties.get(domain.DesignateDomain.NAME))
        self.assertEqual(
            'Test domain',
            self.test_resource.properties.get(
                domain.DesignateDomain.DESCRIPTION))
        self.assertEqual(
            3600,
            self.test_resource.properties.get(domain.DesignateDomain.TTL))
        self.assertEqual(
            'abc@test-domain.com',
            self.test_resource.properties.get(domain.DesignateDomain.EMAIL))

        self.test_resource.data_set = mock.Mock()
        self.test_resource.handle_create()

        args = dict(
            name='test-domain.com',
            description='Test domain',
            ttl=3600,
            email='abc@test-domain.com'
        )

        mock_domain_create.assert_called_once_with(**args)

        # validate physical resource id
        self.assertEqual(mock_resource.id, self.test_resource.resource_id)

    def test_resource_handle_update(self):
        mock_domain_update = self.test_client_plugin.domain_update
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {domain.DesignateDomain.EMAIL: 'xyz@test-domain.com',
                     domain.DesignateDomain.DESCRIPTION: 'updated description',
                     domain.DesignateDomain.TTL: 4200}

        self.test_resource.handle_update(json_snippet=None,
                                         tmpl_diff=None,
                                         prop_diff=prop_diff)

        args = dict(
            id=self.test_resource.resource_id,
            description='updated description',
            ttl=4200,
            email='xyz@test-domain.com'
        )
        mock_domain_update.assert_called_once_with(**args)

    def test_resource_handle_delete(self):
        mock_domain_delete = self.test_client.domains.delete
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_domain_delete.return_value = None

        self.assertEqual('477e8273-60a7-4c41-b683-fdb0bc7cd151',
                         self.test_resource.handle_delete())
        mock_domain_delete.assert_called_once_with(
            self.test_resource.resource_id
        )

    def test_resource_handle_delete_resource_id_is_none(self):
        self.test_resource.resource_id = None
        self.assertIsNone(self.test_resource.handle_delete())

    def test_resource_handle_delete_not_found(self):
        mock_domain_delete = self.test_client.domains.delete
        mock_domain_delete.side_effect = designate_exception.NotFound
        self.assertIsNone(self.test_resource.handle_delete())

    def test_resolve_attributes(self):
        mock_domain = self._get_mock_resource()
        self.test_resource.resource_id = mock_domain.id
        self.test_client.domains.get.return_value = mock_domain
        self.assertEqual(mock_domain.serial,
                         self.test_resource._resolve_attribute(
                             domain.DesignateDomain.SERIAL
                         ))
        self.test_client.domains.get.assert_called_once_with(
            self.test_resource.resource_id
        )

    def test_resource_show_resource(self):
        args = dict(
            name='test',
            description='updated description',
            ttl=4200,
            email='xyz@test-domain.com'
        )

        rsc = domains.Domain(args)
        mock_notification_get = self.test_client.domains.get
        mock_notification_get.return_value = rsc

        self.assertEqual(args,
                         self.test_resource._show_resource(),
                         'Failed to show resource')

    def test_no_ttl(self):
        mock_domain_create = self.test_client_plugin.domain_create
        mock_resource = self._get_mock_resource()
        mock_domain_create.return_value = mock_resource

        self.test_resource.properties.data['ttl'] = None

        self.test_resource.handle_create()
        mock_domain_create.assert_called_once_with(
            name='test-domain.com', description='Test domain',
            email='abc@test-domain.com')

    def test_domain_get_live_state(self):
        return_domain = {
            'name': 'test-domain.com',
            'description': 'Test domain',
            'ttl': 3600,
            'email': 'abc@test-domain.com'
        }
        self.test_client.domains.get.return_value = return_domain
        self.test_resource.resource_id = '1234'

        reality = self.test_resource.get_live_state(
            self.test_resource.properties)

        self.assertEqual(return_domain, reality)

    def test_domain_get_live_state_ttl_equals_zero(self):
        return_domain = {
            'name': 'test-domain.com',
            'description': 'Test domain',
            'ttl': 0,
            'email': 'abc@test-domain.com'
        }
        self.test_client.domains.get.return_value = return_domain
        self.test_resource.resource_id = '1234'

        reality = self.test_resource.get_live_state(
            self.test_resource.properties)

        self.assertEqual(return_domain, reality)
