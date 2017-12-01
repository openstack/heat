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

from designateclient import exceptions as designate_exception
from designateclient.v1 import records
import mock

from heat.engine.resources.openstack.designate import record
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils


sample_template = {
    'heat_template_version': '2015-04-30',
    'resources': {
        'test_resource': {
            'type': 'OS::Designate::Record',
            'properties': {
                'name': 'test-record.com',
                'description': 'Test record',
                'ttl': 3600,
                'type': 'MX',
                'priority': 1,
                'data': '1.1.1.1',
                'domain': '1234567'
            }
        }
    }
}


class DesignateRecordTest(common.HeatTestCase):

    def setUp(self):
        super(DesignateRecordTest, self).setUp()

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

        return value

    def test_resource_validate_properties(self):
        mock_record_create = self.test_client_plugin.record_create
        mock_resource = self._get_mock_resource()
        mock_record_create.return_value = mock_resource

        # validate the properties
        self.assertEqual(
            'test-record.com',
            self.test_resource.properties.get(record.DesignateRecord.NAME))
        self.assertEqual(
            'Test record',
            self.test_resource.properties.get(
                record.DesignateRecord.DESCRIPTION))
        self.assertEqual(
            3600,
            self.test_resource.properties.get(record.DesignateRecord.TTL))
        self.assertEqual(
            'MX',
            self.test_resource.properties.get(record.DesignateRecord.TYPE))
        self.assertEqual(
            1,
            self.test_resource.properties.get(record.DesignateRecord.PRIORITY))
        self.assertEqual(
            '1.1.1.1',
            self.test_resource.properties.get(record.DesignateRecord.DATA))
        self.assertEqual(
            '1234567',
            self.test_resource.properties.get(
                record.DesignateRecord.DOMAIN))

    def test_resource_handle_create_non_mx_or_srv(self):
        mock_record_create = self.test_client_plugin.record_create
        mock_resource = self._get_mock_resource()
        mock_record_create.return_value = mock_resource

        for type in (set(self.test_resource._ALLOWED_TYPES) -
                     set([self.test_resource.MX,
                          self.test_resource.SRV])):
            self.test_resource.properties = args = dict(
                name='test-record.com',
                description='Test record',
                ttl=3600,
                type=type,
                priority=1,
                data='1.1.1.1',
                domain='1234567'
            )

            self.test_resource.handle_create()

            # Make sure priority is set to None for non mx or srv records
            args['priority'] = None
            mock_record_create.assert_called_with(
                **args
            )

            # validate physical resource id
            self.assertEqual(mock_resource.id, self.test_resource.resource_id)

    def test_resource_handle_create_mx_or_srv(self):
        mock_record_create = self.test_client_plugin.record_create
        mock_resource = self._get_mock_resource()
        mock_record_create.return_value = mock_resource

        for type in [self.test_resource.MX, self.test_resource.SRV]:
            self.test_resource.properties = args = dict(
                name='test-record.com',
                description='Test record',
                ttl=3600,
                type=type,
                priority=1,
                data='1.1.1.1',
                domain='1234567'
            )

            self.test_resource.handle_create()

            mock_record_create.assert_called_with(
                **args
            )

            # validate physical resource id
            self.assertEqual(mock_resource.id, self.test_resource.resource_id)

    def test_resource_handle_update_non_mx_or_srv(self):
        mock_record_update = self.test_client_plugin.record_update
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        for type in (set(self.test_resource._ALLOWED_TYPES) -
                     set([self.test_resource.MX,
                          self.test_resource.SRV])):
            prop_diff = args = {
                record.DesignateRecord.DESCRIPTION: 'updated description',
                record.DesignateRecord.TTL: 4200,
                record.DesignateRecord.TYPE: type,
                record.DesignateRecord.DATA: '2.2.2.2',
                record.DesignateRecord.PRIORITY: 1}

            self.test_resource.handle_update(json_snippet=None,
                                             tmpl_diff=None,
                                             prop_diff=prop_diff)

            # priority is not considered for records other than mx or srv
            args.update(dict(
                id=self.test_resource.resource_id,
                priority=None,
                domain='1234567',
            ))
            mock_record_update.assert_called_with(**args)

    def test_resource_handle_update_mx_or_srv(self):
        mock_record_update = self.test_client_plugin.record_update
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        for type in [self.test_resource.MX, self.test_resource.SRV]:
            prop_diff = args = {
                record.DesignateRecord.DESCRIPTION: 'updated description',
                record.DesignateRecord.TTL: 4200,
                record.DesignateRecord.TYPE: type,
                record.DesignateRecord.DATA: '2.2.2.2',
                record.DesignateRecord.PRIORITY: 1}

            self.test_resource.handle_update(json_snippet=None,
                                             tmpl_diff=None,
                                             prop_diff=prop_diff)

            args.update(dict(
                id=self.test_resource.resource_id,
                domain='1234567',
            ))
            mock_record_update.assert_called_with(**args)

    def test_resource_handle_delete(self):
        mock_record_delete = self.test_client_plugin.record_delete
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_record_delete.return_value = None

        self.assertIsNone(self.test_resource.handle_delete())
        mock_record_delete.assert_called_once_with(
            domain='1234567',
            id=self.test_resource.resource_id
        )

    def test_resource_handle_delete_resource_id_is_none(self):
        self.test_resource.resource_id = None
        self.assertIsNone(self.test_resource.handle_delete())

    def test_resource_handle_delete_not_found(self):
        mock_record_delete = self.test_client_plugin.record_delete
        mock_record_delete.side_effect = designate_exception.NotFound
        self.assertIsNone(self.test_resource.handle_delete())

    def test_resource_show_resource(self):
        args = dict(
            name='test-record.com',
            description='Test record',
            ttl=3600,
            type='A',
            priority=1,
            data='1.1.1.1'
        )
        rsc = records.Record(args)
        mock_notification_get = self.test_client_plugin.record_show
        mock_notification_get.return_value = rsc

        self.assertEqual(args,
                         self.test_resource._show_resource(),
                         'Failed to show resource')

    def test_resource_get_live_state(self):
        tmpl = {
            'heat_template_version': '2015-04-30',
            'resources': {
                'test_resource': {
                    'type': 'OS::Designate::Record',
                    'properties': {
                        'name': 'test-record.com',
                        'description': 'Test record',
                        'ttl': 3600,
                        'type': 'MX',
                        'priority': 1,
                        'data': '1.1.1.1',
                        'domain': 'example.com.'
                    }
                }
            }
        }
        s = stack.Stack(
            self.ctx, 'test_stack',
            template.Template(tmpl)
        )

        test_resource = s['test_resource']
        test_resource.resource_id = '1234'
        test_resource.client_plugin().get_domain_id = mock.MagicMock()
        test_resource.client_plugin().get_domain_id.return_value = '1234567'

        test_resource.client().records = mock.MagicMock()
        test_resource.client().records.get.return_value = {
            'type': 'MX',
            'data': '1.1.1.1',
            'ttl': 3600,
            'description': 'test',
            'domain_id': '1234567',
            'name': 'www.example.com.',
            'priority': 0
        }

        reality = test_resource.get_live_state(test_resource.properties)
        expected = {
            'type': 'MX',
            'data': '1.1.1.1',
            'ttl': 3600,
            'description': 'test',
            'priority': 0
        }
        self.assertEqual(expected, reality)
