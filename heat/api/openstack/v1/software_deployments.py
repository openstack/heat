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
from heat.common import serializers
from heat.common import wsgi
from heat.rpc import client as rpc_client


class SoftwareDeploymentController(object):
    """WSGI controller for Software deployments in Heat v1 API.

    Implements the API actions.
    """

    REQUEST_SCOPE = 'software_deployments'

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    def default(self, req, **args):
        raise exc.HTTPNotFound()

    @util.registered_policy_enforce
    def index(self, req):
        """List software deployments."""
        whitelist = {
            'server_id': util.PARAM_TYPE_SINGLE,
        }
        params = util.get_allowed_params(req.params, whitelist)
        sds = self.rpc_client.list_software_deployments(req.context, **params)
        return {'software_deployments': sds}

    @util.registered_policy_enforce
    def metadata(self, req, server_id):
        """List software deployments grouped by the group name.

        This is done for the requested server.
        """
        sds = self.rpc_client.metadata_software_deployments(
            req.context, server_id=server_id)
        return {'metadata': sds}

    @util.registered_policy_enforce
    def show(self, req, deployment_id):
        """Gets detailed information for a software deployment."""
        sd = self.rpc_client.show_software_deployment(req.context,
                                                      deployment_id)
        return {'software_deployment': sd}

    @util.registered_policy_enforce
    def create(self, req, body):
        """Create a new software deployment."""
        create_data = dict((k, body.get(k)) for k in (
            'config_id', 'server_id', 'input_values',
            'action', 'status', 'status_reason', 'stack_user_project_id'))

        sd = self.rpc_client.create_software_deployment(req.context,
                                                        **create_data)
        return {'software_deployment': sd}

    @util.registered_policy_enforce
    def update(self, req, deployment_id, body):
        """Update an existing software deployment."""
        update_data = dict((k, body.get(k)) for k in (
            'config_id', 'input_values', 'output_values', 'action',
            'status', 'status_reason')
            if body.get(k, None) is not None)
        sd = self.rpc_client.update_software_deployment(req.context,
                                                        deployment_id,
                                                        **update_data)
        return {'software_deployment': sd}

    @util.registered_policy_enforce
    def delete(self, req, deployment_id):
        """Delete an existing software deployment."""
        res = self.rpc_client.delete_software_deployment(req.context,
                                                         deployment_id)

        if res is not None:
            raise exc.HTTPBadRequest(res['Error'])

        raise exc.HTTPNoContent()


def create_resource(options):
    """Software deployments resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(
        SoftwareDeploymentController(options), deserializer, serializer)
