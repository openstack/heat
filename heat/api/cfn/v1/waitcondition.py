# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from heat.common import wsgi
from heat.common import context
from heat.rpc import client as rpc_client
from heat.common import identifier
from heat.api.aws import exception
import heat.openstack.common.rpc.common as rpc_common


class WaitConditionController:
    def __init__(self, options):
        self.options = options
        self.engine = rpc_client.EngineClient()

    def update_waitcondition(self, req, body, arn):
        con = req.context
        identity = identifier.ResourceIdentifier.from_arn(arn)
        try:
            md = self.engine.metadata_update(
                con,
                stack_id=dict(identity.stack()),
                resource_name=identity.resource_name,
                metadata=body)
        except rpc_common.RemoteError as ex:
            return exception.map_remote_error(ex)

        return {'resource': identity.resource_name, 'metadata': md}


def create_resource(options):
    """
    Stacks resource factory method.
    """
    deserializer = wsgi.JSONRequestDeserializer()
    return wsgi.Resource(WaitConditionController(options), deserializer)
