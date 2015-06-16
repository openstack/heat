# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
import oslo_messaging as messaging

from heat.rpc import api as rpc_api
from heat.rpc import listener_client as rpc_client
from heat.tests import common


class ListenerClientTest(common.HeatTestCase):

    @mock.patch('heat.common.messaging.get_rpc_client',
                return_value=mock.Mock())
    def test_engine_alive_ok(self, rpc_client_method):
        mock_rpc_client = rpc_client_method.return_value
        mock_prepare_method = mock_rpc_client.prepare
        mock_prepare_client = mock_prepare_method.return_value
        mock_cnxt = mock.Mock()

        listener_client = rpc_client.EngineListenerClient('engine-007')
        rpc_client_method.assert_called_once_with(
            version=rpc_client.EngineListenerClient.BASE_RPC_API_VERSION,
            topic=rpc_api.LISTENER_TOPIC, server='engine-007',
        )
        mock_prepare_method.assert_called_once_with(timeout=2)
        self.assertEqual(mock_prepare_client,
                         listener_client._client,
                         "Failed to create RPC client")

        ret = listener_client.is_alive(mock_cnxt)
        self.assertTrue(ret)
        mock_prepare_client.call.assert_called_once_with(mock_cnxt,
                                                         'listening')

    @mock.patch('heat.common.messaging.get_rpc_client',
                return_value=mock.Mock())
    def test_engine_alive_timeout(self, rpc_client_method):
        mock_rpc_client = rpc_client_method.return_value
        mock_prepare_method = mock_rpc_client.prepare
        mock_prepare_client = mock_prepare_method.return_value
        mock_cnxt = mock.Mock()

        listener_client = rpc_client.EngineListenerClient('engine-007')
        rpc_client_method.assert_called_once_with(
            version=rpc_client.EngineListenerClient.BASE_RPC_API_VERSION,
            topic=rpc_api.LISTENER_TOPIC, server='engine-007',
        )
        mock_prepare_method.assert_called_once_with(timeout=2)
        self.assertEqual(mock_prepare_client,
                         listener_client._client,
                         "Failed to create RPC client")

        mock_prepare_client.call.side_effect = messaging.MessagingTimeout(
            'too slow')
        ret = listener_client.is_alive(mock_cnxt)
        self.assertFalse(ret)
        mock_prepare_client.call.assert_called_once_with(mock_cnxt,
                                                         'listening')
