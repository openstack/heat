#
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

"""Client side of the heat worker RPC API."""

from oslo_config import cfg
import oslo_messaging as messaging

from heat.common import messaging as rpc_messaging
from heat.rpc import api as rpc_api

cfg.CONF.import_opt('engine_life_check_timeout', 'heat.common.config')


class EngineListenerClient(object):
    """Client side of the heat listener RPC API.

    API version history::

        1.0 - Initial version.
    """

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, engine_id):
        _client = rpc_messaging.get_rpc_client(
            topic=rpc_api.LISTENER_TOPIC,
            version=self.BASE_RPC_API_VERSION,
            server=engine_id)
        self._client = _client.prepare(
            timeout=cfg.CONF.engine_life_check_timeout)

    def is_alive(self, ctxt):
        try:
            return self._client.call(ctxt, 'listening')
        except messaging.MessagingTimeout:
            return False
