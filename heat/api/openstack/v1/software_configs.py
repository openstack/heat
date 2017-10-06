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

import six
from webob import exc

from heat.api.openstack.v1 import util
from heat.common import context
from heat.common import param_utils
from heat.common import serializers
from heat.common import wsgi
from heat.rpc import api as rpc_api
from heat.rpc import client as rpc_client


class SoftwareConfigController(object):
    """WSGI controller for Software config in Heat v1 API.

    Implements the API actions.
    """

    REQUEST_SCOPE = 'software_configs'

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    def default(self, req, **args):
        raise exc.HTTPNotFound()

    def _extract_bool_param(self, name, value):
        try:
            return param_utils.extract_bool(name, value)
        except ValueError as e:
            raise exc.HTTPBadRequest(six.text_type(e))

    def _index(self, req, use_admin_cnxt=False):
        whitelist = {
            'limit': util.PARAM_TYPE_SINGLE,
            'marker': util.PARAM_TYPE_SINGLE
        }
        params = util.get_allowed_params(req.params, whitelist)

        if use_admin_cnxt:
            cnxt = context.get_admin_context()
        else:
            cnxt = req.context
        scs = self.rpc_client.list_software_configs(cnxt,
                                                    **params)
        return {'software_configs': scs}

    @util.registered_policy_enforce
    def global_index(self, req):
        return self._index(req, use_admin_cnxt=True)

    @util.registered_policy_enforce
    def index(self, req):
        """Lists summary information for all software configs."""
        global_tenant = False
        name = rpc_api.PARAM_GLOBAL_TENANT
        if name in req.params:
            global_tenant = self._extract_bool_param(
                name,
                req.params.get(name))

        if global_tenant:
            return self.global_index(req, req.context.tenant_id)

        return self._index(req)

    @util.registered_policy_enforce
    def show(self, req, config_id):
        """Gets detailed information for a software config."""
        sc = self.rpc_client.show_software_config(
            req.context, config_id)
        return {'software_config': sc}

    @util.registered_policy_enforce
    def create(self, req, body):
        """Create a new software config."""
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

    @util.registered_policy_enforce
    def delete(self, req, config_id):
        """Delete an existing software config."""
        res = self.rpc_client.delete_software_config(req.context, config_id)

        if res is not None:
            raise exc.HTTPBadRequest(res['Error'])

        raise exc.HTTPNoContent()


def create_resource(options):
    """Software configs resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(
        SoftwareConfigController(options), deserializer, serializer)
