# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
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

from heat.common import messaging
from heat.rpc import worker_api


class WorkerClient(object):
    """Client side of the heat worker RPC API.

    API version history::

        1.0 - Initial version.
        1.1 - Added check_resource.
        1.2 - Add adopt data argument to check_resource.
        1.3 - Added cancel_check_resource API.
        1.4 - Add converge argument to check_resource
    """

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        self._client = messaging.get_rpc_client(
            topic=worker_api.TOPIC,
            version=self.BASE_RPC_API_VERSION)

    @staticmethod
    def make_msg(method, **kwargs):
        return method, kwargs

    def cast(self, ctxt, msg, version=None):
        method, kwargs = msg
        if version is not None:
            client = self._client.prepare(version=version)
        else:
            client = self._client
        client.cast(ctxt, method, **kwargs)

    def check_resource(self, ctxt, resource_id,
                       current_traversal, data, is_update, adopt_stack_data,
                       converge=False):
        self.cast(ctxt,
                  self.make_msg(
                      'check_resource', resource_id=resource_id,
                      current_traversal=current_traversal, data=data,
                      is_update=is_update, adopt_stack_data=adopt_stack_data,
                      converge=converge
                  ),
                  version='1.4')

    def cancel_check_resource(self, ctxt, stack_id, engine_id):
        """Send check-resource cancel message.

        Sends a cancel message to given heat engine worker.
        """

        _client = messaging.get_rpc_client(
            topic=worker_api.TOPIC,
            version=self.BASE_RPC_API_VERSION,
            server=engine_id)

        method, kwargs = self.make_msg('cancel_check_resource',
                                       stack_id=stack_id)
        cl = _client.prepare(version='1.3')
        cl.cast(ctxt, method, **kwargs)
