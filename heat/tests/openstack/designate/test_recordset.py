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
import mock

from heat.common import exception
from heat.engine.resources.openstack.designate import recordset
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils


sample_template = {
    'heat_template_version': '2015-04-30',
    'resources': {
        'test_resource': {
            'type': 'OS::Designate::RecordSet',
            'properties': {
                'name': 'test-record.com',
                'description': 'Test record',
                'ttl': 3600,
                'type': 'A',
                'records': ['1.1.1.1'],
                'zone': '1234567'
            }
        }
    }
}


class DesignateRecordSetTest(common.HeatTestCase):

    def setUp(self):
        super(DesignateRecordSetTest, self).setUp()

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
        value = {}
        value['id'] = '477e8273-60a7-4c41-b683-fdb0bc7cd152'

        return value

    def test_resource_validate_properties(self):
        mock_record_create = self.test_client_plugin.record_create
        mock_resource = self._get_mock_resource()
        mock_record_create.return_value = mock_resource

        # validate the properties
        self.assertEqual(
            'test-record.com',
            self.test_resource.properties.get(
                recordset.DesignateRecordSet.NAME))
        self.assertEqual(
            'Test record',
            self.test_resource.properties.get(
                recordset.DesignateRecordSet.DESCRIPTION))
        self.assertEqual(
            3600,
            self.test_resource.properties.get(
                recordset.DesignateRecordSet.TTL))
        self.assertEqual(
            'A',
            self.test_resource.properties.get(
                recordset.DesignateRecordSet.TYPE))
        self.assertEqual(
            ['1.1.1.1'],
            self.test_resource.properties.get(
                recordset.DesignateRecordSet.RECORDS))
        self.assertEqual(
            '1234567',
            self.test_resource.properties.get(
                recordset.DesignateRecordSet.ZONE))

    def test_resource_handle_create(self):
        mock_record_create = self.test_client.recordsets.create
        mock_resource = self._get_mock_resource()
        mock_record_create.return_value = mock_resource

        self.test_resource.properties = args = dict(
            name='test-record.com',
            description='Test record',
            ttl=3600,
            type='A',
            records=['1.1.1.1'],
            zone='1234567'
        )

        self.test_resource.handle_create()
        args['type_'] = args.pop('type')
        mock_record_create.assert_called_with(
            **args
        )

        # validate physical resource id
        self.assertEqual(mock_resource['id'], self.test_resource.resource_id)

    def _mock_check_status_active(self):
        self.test_client.recordsets.get.side_effect = [
            {'status': 'PENDING'},
            {'status': 'ACTIVE'},
            {'status': 'ERROR'}
        ]

    def test_check_create_complete(self):
        self._mock_check_status_active()
        self.assertFalse(self.test_resource.check_create_complete())
        self.assertTrue(self.test_resource.check_create_complete())
        ex = self.assertRaises(exception.ResourceInError,
                               self.test_resource.check_create_complete)
        self.assertIn('Error in RecordSet',
                      ex.message)

    def test_resource_handle_update(self):
        mock_record_update = self.test_client.recordsets.update
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = args = {
            recordset.DesignateRecordSet.DESCRIPTION: 'updated description',
            recordset.DesignateRecordSet.TTL: 4200,
            recordset.DesignateRecordSet.TYPE: 'B',
            recordset.DesignateRecordSet.RECORDS: ['2.2.2.2']
        }
        self.test_resource.handle_update(json_snippet=None,
                                         tmpl_diff=None,
                                         prop_diff=prop_diff)

        args['type_'] = args.pop('type')
        mock_record_update.assert_called_with(
            zone='1234567',
            recordset='477e8273-60a7-4c41-b683-fdb0bc7cd151',
            values=args)

    def test_check_update_complete(self):
        self._mock_check_status_active()
        self.assertFalse(self.test_resource.check_update_complete())
        self.assertTrue(self.test_resource.check_update_complete())
        ex = self.assertRaises(exception.ResourceInError,
                               self.test_resource.check_create_complete)
        self.assertIn('Error in RecordSet',
                      ex.message)

    def test_resource_handle_delete(self):
        mock_record_delete = self.test_client.recordsets.delete
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_record_delete.return_value = None

        self.assertIsNone(self.test_resource.handle_delete())
        mock_record_delete.assert_called_once_with(
            zone='1234567',
            recordset=self.test_resource.resource_id
        )

    def test_resource_handle_delete_resource_id_is_none(self):
        self.test_resource.resource_id = None
        self.assertIsNone(self.test_resource.handle_delete())

    def test_resource_handle_delete_not_found(self):
        mock_record_delete = self.test_client_plugin.record_delete
        mock_record_delete.side_effect = designate_exception.NotFound
        self.assertIsNone(self.test_resource.handle_delete())

    def test_check_delete_complete(self):
        self.test_resource.resource_id = self._get_mock_resource()['id']
        self._mock_check_status_active()
        self.assertFalse(self.test_resource.check_delete_complete())
        self.assertTrue(self.test_resource.check_delete_complete())
        ex = self.assertRaises(exception.ResourceInError,
                               self.test_resource.check_create_complete)
        self.assertIn('Error in RecordSet',
                      ex.message)

    def test_resource_show_resource(self):
        args = dict(
            name='test-record.com',
            description='Test record',
            ttl=3600,
            type='A',
            records=['1.1.1.1']
        )
        mock_get = self.test_client.recordsets.get
        mock_get.return_value = args

        self.assertEqual(args,
                         self.test_resource._show_resource(),
                         'Failed to show resource')
