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

import json

from webob.exc import Response

from heat.common import wsgi
from heat.common import context
from heat.rpc import client as rpc_client
from heat.openstack.common import rpc
from heat.common import identifier


def json_response(http_status, data):
    """Create a JSON response with a specific HTTP code."""
    response = Response(json.dumps(data))
    response.status = http_status
    response.content_type = 'application/json'
    return response


def json_error(http_status, message):
    """Create a JSON error response."""
    body = {'error': message}
    return json_response(http_status, body)


class WaitConditionController:
    def __init__(self, options):
        self.options = options
        self.engine = rpc_client.EngineClient()

    def update_waitcondition(self, req, body, arn):
        con = req.context
        identity = identifier.ResourceIdentifier.from_arn(arn)
        [error, metadata] = self.engine.metadata_update(con,
                                 stack_id=identity.stack_id,
                                 resource_name=identity.resource_name,
                                 metadata=body)
        if error:
            if error == 'stack':
                return json_error(404,
                        'The stack "%s" does not exist.' % identity.stack_id)
            else:
                return json_error(404,
                        'The resource "%s" does not exist.' %
                        identity.resource_name)
        return json_response(201, {
            'resource': identity.resource_name,
            'metadata': body,
        })


def create_resource(options):
    """
    Stacks resource factory method.
    """
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(WaitConditionController(options), deserializer,
                         serializer)
