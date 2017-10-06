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
from heat.common.i18n import _
from heat.common import serializers
from heat.common import wsgi
from heat.rpc import client as rpc_client


class ActionController(object):
    """WSGI controller for Actions in Heat v1 API.

    Implements the API for stack actions
    """
    # Define request scope (must match what is in policy.json or policies in
    # code)
    REQUEST_SCOPE = 'actions'

    ACTIONS = (
        SUSPEND, RESUME, CHECK,
        CANCEL_UPDATE, CANCEL_WITHOUT_ROLLBACK
    ) = (
        'suspend', 'resume', 'check',
        'cancel_update', 'cancel_without_rollback'
    )

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    @util.registered_identified_stack
    def action(self, req, identity, body=None):
        """Performs a specified action on a stack.

        The body is expecting to contain exactly one item whose key specifies
        the action.
        """
        body = body or {}
        if len(body) < 1:
            raise exc.HTTPBadRequest(_("No action specified"))

        if len(body) > 1:
            raise exc.HTTPBadRequest(_("Multiple actions specified"))

        ac = next(six.iterkeys(body))
        if ac not in self.ACTIONS:
            raise exc.HTTPBadRequest(_("Invalid action %s specified") % ac)

        if ac == self.SUSPEND:
            self.rpc_client.stack_suspend(req.context, identity)
        elif ac == self.RESUME:
            self.rpc_client.stack_resume(req.context, identity)
        elif ac == self.CHECK:
            self.rpc_client.stack_check(req.context, identity)
        elif ac == self.CANCEL_UPDATE:
            self.rpc_client.stack_cancel_update(req.context, identity,
                                                cancel_with_rollback=True)
        elif ac == self.CANCEL_WITHOUT_ROLLBACK:
            self.rpc_client.stack_cancel_update(req.context, identity,
                                                cancel_with_rollback=False)
        else:
            raise exc.HTTPInternalServerError(_("Unexpected action %s") % ac)


def create_resource(options):
    """Actions action factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(ActionController(options), deserializer, serializer)
