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
from heat.common.i18n import _
from heat.common import serializers
from heat.common import wsgi
from heat.rpc import client as rpc_client


class ActionController(object):
    """WSGI controller for Actions in Heat v1 API.

    Implements the API for stack actions
    """
    # Define request scope (must match what is in policy.yaml or policies in
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

    # Don't enforce policy on this API, as potentially differing policies
    # will be enforced on individual actions.
    def action(self, req, tenant_id, stack_name, stack_id, body=None):
        """Performs a specified action on a stack.

        The body is expecting to contain exactly one item whose key specifies
        the action.
        """
        body = body or {}
        if len(body) < 1:
            raise exc.HTTPBadRequest(_("No action specified"))

        if len(body) > 1:
            raise exc.HTTPBadRequest(_("Multiple actions specified"))

        ac = next(iter(body.keys()))
        if ac not in self.ACTIONS:
            raise exc.HTTPBadRequest(_("Invalid action %s specified") % ac)

        do_action = getattr(self, ac, None)
        if do_action is None:
            raise exc.HTTPInternalServerError(_("Unexpected action %s") % ac)

        do_action(req, tenant_id=tenant_id,
                  stack_name=stack_name, stack_id=stack_id,
                  body=body)

    @util.registered_identified_stack
    def suspend(self, req, identity, body=None):
        self.rpc_client.stack_suspend(req.context, identity)

    @util.registered_identified_stack
    def resume(self, req, identity, body=None):
        self.rpc_client.stack_resume(req.context, identity)

    @util.registered_identified_stack
    def check(self, req, identity, body=None):
        self.rpc_client.stack_check(req.context, identity)

    @util.registered_identified_stack
    def cancel_update(self, req, identity, body=None):
        self.rpc_client.stack_cancel_update(req.context, identity,
                                            cancel_with_rollback=True)

    @util.registered_identified_stack
    def cancel_without_rollback(self, req, identity, body=None):
        self.rpc_client.stack_cancel_update(req.context, identity,
                                            cancel_with_rollback=False)


def create_resource(options):
    """Actions action factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(ActionController(options), deserializer, serializer)
