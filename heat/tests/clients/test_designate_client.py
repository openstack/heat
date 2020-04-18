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

from unittest import mock

from designateclient import client as designate_client

from heat.common import exception as heat_exception
from heat.engine.clients.os import designate as client
from heat.tests import common


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
            session=session, region_name='region1',
            version='2')


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
