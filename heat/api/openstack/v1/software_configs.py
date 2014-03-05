
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

from webob import exc

from heat.api.openstack.v1 import util
from heat.common import wsgi
from heat.rpc import client as rpc_client


class SoftwareConfigController(object):
    """
    WSGI controller for Software config in Heat v1 API
    Implements the API actions
    """

    REQUEST_SCOPE = 'software_configs'

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    def default(self, req, **args):
        raise exc.HTTPNotFound()

    @util.policy_enforce
    def show(self, req, config_id):
        """
        Gets detailed information for a software config
        """
        sc = self.rpc_client.show_software_config(
            req.context, config_id)
        return {'software_config': sc}

    @util.policy_enforce
    def create(self, req, body):
        """
        Create a new software config
        """
        create_data = {
            'name': body.get('name'),
            'group': body.get('group'),
            'config': body.get('config'),
            'inputs': body.get('inputs'),
            'outputs': body.get('outputs'),
            'options': body.get('options'),
        }
        sc = self.rpc_client.create_software_config(
            req.context, **create_data)
        return {'software_config': sc}

    @util.policy_enforce
    def delete(self, req, config_id):
        """
        Delete an existing software config
        """
        res = self.rpc_client.delete_software_config(req.context, config_id)

        if res is not None:
            raise exc.HTTPBadRequest(res['Error'])

        raise exc.HTTPNoContent()


def create_resource(options):
    """
    Software configs resource factory method.
    """
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(
        SoftwareConfigController(options), deserializer, serializer)
