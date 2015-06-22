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

from designateclient import exceptions as designate_exceptions
from designateclient import v1 as designate_client

from heat.common import exception as heat_exception
from heat.engine.clients.os import designate as client
from heat.tests import common


class DesignateDomainConstraintTest(common.HeatTestCase):

    def test_expected_exceptions(self):
        self.assertEqual((heat_exception.EntityNotFound,),
                         client.DesignateDomainConstraint.expected_exceptions,
                         "DesignateDomainConstraint expected exceptions error")

    def test_constrain(self):
        constrain = client.DesignateDomainConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_domain_id.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constrain.validate_with_client(client_mock,
                                                         'domain_1'))

        client_plugin_mock.get_domain_id.assert_called_once_with('domain_1')


class DesignateClientPluginTest(common.HeatTestCase):
    @mock.patch.object(designate_client, 'Client')
    @mock.patch.object(client.DesignateClientPlugin, '_get_client_args')
    def test_client(self,
                    get_client_args,
                    client_designate):
        args = dict(
            auth_url='auth_url',
            project_id='project_id',
            token=lambda: '',
            os_endpoint='os_endpoint',
            cacert='cacert',
            insecure='insecure'
        )
        get_client_args.return_value = args

        client_plugin = client.DesignateClientPlugin(
            context=mock.MagicMock()
        )
        client_plugin.client()

        # Make sure the right args are created
        get_client_args.assert_called_once_with(
            service_name='designate',
            service_type='dns'
        )

        # Make sure proper client is created with expected args
        client_designate.assert_called_once_with(
            auth_url='auth_url',
            project_id='project_id',
            token='',
            endpoint='os_endpoint',
            cacert='cacert',
            insecure='insecure'
        )


class DesignateClientPluginDomainTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
    sample_name = 'test-domain.com'

    def _get_mock_domain(self):
        domain = mock.MagicMock()
        domain.id = self.sample_uuid
        domain.name = self.sample_name
        return domain

    def setUp(self):
        super(DesignateClientPluginDomainTest, self).setUp()
        self._client = mock.MagicMock()
        self.client_plugin = client.DesignateClientPlugin(
            context=mock.MagicMock()
        )

    @mock.patch.object(client.DesignateClientPlugin, 'client')
    def test_get_domain_id(self, client_designate):
        self._client.domains.get.return_value = self._get_mock_domain()
        client_designate.return_value = self._client

        self.assertEqual(self.sample_uuid,
                         self.client_plugin.get_domain_id(self.sample_uuid))
        self._client.domains.get.assert_called_once_with(
            self.sample_uuid)

    @mock.patch.object(client.DesignateClientPlugin, 'client')
    def test_get_domain_id_not_found(self, client_designate):
        self._client.domains.get.side_effect = (designate_exceptions
                                                .NotFound)
        client_designate.return_value = self._client

        ex = self.assertRaises(heat_exception.EntityNotFound,
                               self.client_plugin.get_domain_id,
                               self.sample_uuid)
        msg = ("The Designate Domain (%(name)s) could not be found." %
               {'name': self.sample_uuid})
        self.assertEqual(msg, six.text_type(ex))
        self._client.domains.get.assert_called_once_with(
            self.sample_uuid)

    @mock.patch.object(client.DesignateClientPlugin, 'client')
    def test_get_domain_id_by_name(self, client_designate):
        self._client.domains.get.side_effect = (designate_exceptions
                                                .NotFound)
        self._client.domains.list.return_value = [self._get_mock_domain()]
        client_designate.return_value = self._client

        self.assertEqual(self.sample_uuid,
                         self.client_plugin.get_domain_id(self.sample_name))

        self._client.domains.get.assert_called_once_with(
            self.sample_name)
        self._client.domains.list.assert_called_once_with()

    @mock.patch.object(client.DesignateClientPlugin, 'client')
    def test_get_domain_id_by_name_not_found(self, client_designate):
        self._client.domains.get.side_effect = (designate_exceptions
                                                .NotFound)
        self._client.domains.list.return_value = []
        client_designate.return_value = self._client

        ex = self.assertRaises(heat_exception.EntityNotFound,
                               self.client_plugin.get_domain_id,
                               self.sample_name)
        msg = ("The Designate Domain (%(name)s) could not be found." %
               {'name': self.sample_name})
        self.assertEqual(msg, six.text_type(ex))

        self._client.domains.get.assert_called_once_with(
            self.sample_name)
        self._client.domains.list.assert_called_once_with()

    @mock.patch.object(client.DesignateClientPlugin, 'client')
    @mock.patch('designateclient.v1.domains.Domain')
    def test_domain_create(self, mock_domain, client_designate):
        self._client.domains.create.return_value = None
        client_designate.return_value = self._client

        domain = dict(
            name='test-domain.com',
            description='updated description',
            ttl=4200,
            email='xyz@test-domain.com'
        )

        mock_sample_domain = mock.Mock()
        mock_domain.return_value = mock_sample_domain

        self.client_plugin.domain_create(**domain)

        # Make sure domain entity is created with right arguments
        mock_domain.assert_called_once_with(**domain)
        self._client.domains.create.assert_called_once_with(
            mock_sample_domain)

    @mock.patch.object(client.DesignateClientPlugin, 'client')
    def test_domain_update(self, client_designate):
        self._client.domains.update.return_value = None
        mock_domain = self._get_mock_domain()
        self._client.domains.get.return_value = mock_domain

        client_designate.return_value = self._client

        domain = dict(
            id='sample-id',
            description='updated description',
            ttl=4200,
            email='xyz@test-domain.com'
        )

        self.client_plugin.domain_update(**domain)

        self._client.domains.get.assert_called_once_with(
            mock_domain.id)

        for key in domain.keys():
            setattr(mock_domain, key, domain[key])

        self._client.domains.update.assert_called_once_with(
            mock_domain)
