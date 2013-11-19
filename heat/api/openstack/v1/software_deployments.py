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

from webob import exc

from heat.api.openstack.v1 import util
from heat.common import wsgi
from heat.rpc import client as rpc_client


class SoftwareDeploymentController(object):
    """
    WSGI controller for Software deployments in Heat v1 API
    Implements the API actions
    """

    REQUEST_SCOPE = 'software_deployments'

    def __init__(self, options):
        self.options = options
        self.engine = rpc_client.EngineClient()

    def default(self, req, **args):
        raise exc.HTTPNotFound()

    @util.policy_enforce
    def index(self, req):
        """
        List software deployments.
        """
        whitelist = {
            'server_id': 'single',
        }
        params = util.get_allowed_params(req.params, whitelist)
        sds = self.engine.list_software_deployments(req.context, **params)
        return {'software_deployments': sds}

    @util.policy_enforce
    def show(self, req, deployment_id):
        """
        Gets detailed information for a software deployment
        """
        sd = self.engine.show_software_deployment(
            req.context, deployment_id)
        return {'software_deployment': sd}

    @util.policy_enforce
    def create(self, req, body):
        """
        Create a new software deployment
        """
        create_data = {
            'config_id': body.get('config_id'),
            'server_id': body.get('server_id'),
            'input_values': body.get('input_values'),
            'signal_id': body.get('signal_id'),
            'action': body.get('action'),
            'status': body.get('status'),
            'status_reason': body.get('status_reason'),
        }
        sd = self.engine.create_software_deployment(
            req.context, **create_data)
        return {'software_deployment': sd}

    @util.policy_enforce
    def update(self, req, deployment_id, body):
        """
        Update an existing software deployment
        """
        update_data = {
            'config_id': body.get('config_id'),
            'input_values': body.get('input_values'),
            'output_values': body.get('output_values'),
            'action': body.get('action'),
            'status': body.get('status'),
            'status_reason': body.get('status_reason'),
        }
        sd = self.engine.update_software_deployment(
            req.context, deployment_id, **update_data)
        return {'software_deployment': sd}

    @util.policy_enforce
    def delete(self, req, deployment_id):
        """
        Delete an existing software deployment
        """
        res = self.engine.delete_software_deployment(
            req.context, deployment_id)

        if res is not None:
            raise exc.HTTPBadRequest(res['Error'])

        raise exc.HTTPNoContent()


def create_resource(options):
    """
    Software deployments resource factory method.
    """
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(
        SoftwareDeploymentController(options), deserializer, serializer)
