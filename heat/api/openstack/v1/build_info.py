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

from oslo_config import cfg

from heat.api.openstack.v1 import util
from heat.common import serializers
from heat.common import wsgi
from heat.rpc import client as rpc_client


class BuildInfoController(object):
    """WSGI controller for BuildInfo in Heat v1 API.

    Returns build information for current app.
    """
    # Define request scope (must match what is in policy.json or policies in
    # code)
    REQUEST_SCOPE = 'build_info'

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    @util.registered_policy_enforce
    def build_info(self, req):
        engine_revision = self.rpc_client.get_revision(req.context)
        build_info = {
            'api': {'revision': cfg.CONF.revision['heat_revision']},
            'engine': {'revision': engine_revision}
        }

        return build_info


def create_resource(options):
    """BuildInfo factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(BuildInfoController(options), deserializer,
                         serializer)
