
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


class ActionController(object):
    """
    WSGI controller for Actions in Heat v1 API
    Implements the API for stack actions
    """
    # Define request scope (must match what is in policy.json)
    REQUEST_SCOPE = 'actions'

    ACTIONS = (SUSPEND, RESUME) = ('suspend', 'resume')

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    @util.identified_stack
    def action(self, req, identity, body={}):
        """
        Performs a specified action on a stack, the body is expecting to
        contain exactly one item whose key specifies the action
        """

        if len(body) < 1:
            raise exc.HTTPBadRequest(_("No action specified"))

        if len(body) > 1:
            raise exc.HTTPBadRequest(_("Multiple actions specified"))

        ac = body.keys()[0]
        if ac not in self.ACTIONS:
            raise exc.HTTPBadRequest(_("Invalid action %s specified") % ac)

        if ac == self.SUSPEND:
            self.rpc_client.stack_suspend(req.context, identity)
        elif ac == self.RESUME:
            self.rpc_client.stack_resume(req.context, identity)
        else:
            raise exc.HTTPInternalServerError(_("Unexpected action %s") % ac)


def create_resource(options):
    """
    Actions action factory method.
    """
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(ActionController(options), deserializer, serializer)
