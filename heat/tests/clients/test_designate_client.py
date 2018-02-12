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

from designateclient import exceptions as designate_exceptions
from designateclient import v1 as designate_client
import mock
import six

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
    def test_client(self, client_designate):
        context = mock.Mock()
        session = mock.Mock()
        context.keystone_session = session
        client_plugin = client.DesignateClientPlugin(context)
        self.patchobject(client_plugin, '_get_region_name',
                         return_value='region1')
        client_plugin.client()

        # Make sure proper client is created with expected args
        client_designate.assert_called_once_with(
            endpoint_type='publicURL', service_type='dns',
            session=session, region_name='region1'
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


class DesignateClientPluginRecordTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
    sample_domain_id = '477e8273-60a7-4c41-b683-fdb0bc7cd153'

    def _get_mock_record(self):
        record = mock.MagicMock()
        record.id = self.sample_uuid
        record.domain_id = self.sample_domain_id
        return record

    def setUp(self):
        super(DesignateClientPluginRecordTest, self).setUp()
        self._client = mock.MagicMock()
        self.client_plugin = client.DesignateClientPlugin(
            context=mock.MagicMock()
        )
        self.client_plugin.get_domain_id = mock.Mock(
            return_value=self.sample_domain_id)

    @mock.patch.object(client.DesignateClientPlugin, 'client')
    @mock.patch('designateclient.v1.records.Record')
    def test_record_create(self, mock_record, client_designate):
        self._client.records.create.return_value = None
        client_designate.return_value = self._client

        record = dict(
            name='test-record.com',
            description='updated description',
            ttl=4200,
            type='',
            priority=1,
            data='1.1.1.1',
            domain=self.sample_domain_id
        )

        mock_sample_record = mock.Mock()
        mock_record.return_value = mock_sample_record

        self.client_plugin.record_create(**record)

        # Make sure record entity is created with right arguments
        domain_id = record.pop('domain')
        mock_record.assert_called_once_with(**record)
        self._client.records.create.assert_called_once_with(
            domain_id,
            mock_sample_record)

    @mock.patch.object(client.DesignateClientPlugin, 'client')
    @mock.patch('designateclient.v1.records.Record')
    def test_record_update(self, mock_record, client_designate):
        self._client.records.update.return_value = None
        mock_record = self._get_mock_record()
        self._client.records.get.return_value = mock_record

        client_designate.return_value = self._client

        record = dict(
            id=self.sample_uuid,
            name='test-record.com',
            description='updated description',
            ttl=4200,
            type='',
            priority=1,
            data='1.1.1.1',
            domain=self.sample_domain_id
        )

        self.client_plugin.record_update(**record)

        self._client.records.get.assert_called_once_with(
            self.sample_domain_id,
            self.sample_uuid)

        for key in record.keys():
            setattr(mock_record, key, record[key])

        self._client.records.update.assert_called_once_with(
            self.sample_domain_id,
            mock_record)

    @mock.patch.object(client.DesignateClientPlugin, 'client')
    @mock.patch('designateclient.v1.records.Record')
    def test_record_delete(self, mock_record, client_designate):
        self._client.records.delete.return_value = None
        client_designate.return_value = self._client

        record = dict(
            id=self.sample_uuid,
            domain=self.sample_domain_id
        )

        self.client_plugin.record_delete(**record)

        self._client.records.delete.assert_called_once_with(
            self.sample_domain_id,
            self.sample_uuid)

    @mock.patch.object(client.DesignateClientPlugin, 'client')
    @mock.patch('designateclient.v1.records.Record')
    def test_record_delete_domain_not_found(self, mock_record,
                                            client_designate):
        self._client.records.delete.return_value = None
        self.client_plugin.get_domain_id.side_effect = (
            heat_exception.EntityNotFound)
        client_designate.return_value = self._client

        record = dict(
            id=self.sample_uuid,
            domain=self.sample_domain_id
        )

        self.client_plugin.record_delete(**record)

        self.assertFalse(self._client.records.delete.called)

    @mock.patch.object(client.DesignateClientPlugin, 'client')
    @mock.patch('designateclient.v1.records.Record')
    def test_record_show(self, mock_record, client_designate):
        self._client.records.get.return_value = None
        client_designate.return_value = self._client

        record = dict(
            id=self.sample_uuid,
            domain=self.sample_domain_id
        )

        self.client_plugin.record_show(**record)

        self._client.records.get.assert_called_once_with(
            self.sample_domain_id,
            self.sample_uuid)


class DesignateZoneConstraintTest(common.HeatTestCase):

    def test_expected_exceptions(self):
        self.assertEqual((heat_exception.EntityNotFound,),
                         client.DesignateZoneConstraint.expected_exceptions,
                         "DesignateZoneConstraint expected exceptions error")

    def test_constrain(self):
        constrain = client.DesignateZoneConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_zone_id.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constrain.validate_with_client(client_mock,
                                                         'zone_1'))

        client_plugin_mock.get_zone_id.assert_called_once_with('zone_1')
