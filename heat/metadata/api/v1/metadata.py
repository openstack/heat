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
from heat.engine import rpcapi as engine_rpcapi
from heat.openstack.common import rpc


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


class MetadataController:
    def __init__(self, options):
        self.options = options
        self.engine_rpcapi = engine_rpcapi.EngineAPI()

    def entry_point(self, req):
        return {
            'name': 'Heat Metadata Server API',
            'version': '1',
        }

    def list_stacks(self, req):
        con = context.get_admin_context()
        resp = self.engine_rpcapi.metadata_list_stacks(con)
        return resp

    def list_resources(self, req, stack_name):
        con = context.get_admin_context()
        resources = self.engine_rpcapi.metadata_list_resources(con,
                         stack_name=stack_name)
        if resources:
            return resources
        else:
            return json_error(404,
                              'The stack "%s" does not exist.' % stack_name)

    def get_resource(self, req, stack_name, resource_name):
        con = context.get_admin_context()
        [error, metadata] = self.engine_rpcapi.metadata_get_resource(con,
                                 stack_name=stack_name,
                                 resource_name=resource_name)
        if error:
            if error == 'stack':
                return json_error(404,
                            'The stack "%s" does not exist.' % stack_name)
            else:
                return json_error(404,
                       'The resource "%s" does not exist.' % resource_name)
        return metadata

    def update_metadata(self, req, body, stack_id, resource_name):
        con = context.get_admin_context()
        [error, metadata] = self.engine_rpcapi.metadata_update(con,
                                 stack_id=stack_id,
                                 resource_name=resource_name,
                                 metadata=body)
        if error:
            if error == 'stack':
                return json_error(404,
                        'The stack "%s" does not exist.' % stack_id)
            else:
                return json_error(404,
                        'The resource "%s" does not exist.' % resource_name)
        return json_response(201, {
            'resource': resource_name,
            'metadata': body,
        })

    def create_event(self, req, body=None):
        con = context.get_admin_context()
        [error, event] = self.engine_rpcapi.event_create(con, event=body)
        if error:
            return json_error(400, error)
        return json_response(201, event)

    def create_watch_data(self, req, body, watch_name):
        con = context.get_admin_context()
        [error, watch_data] = self.engine_rpcapi.create_watch_data(con,
                                   watch_name=watch_name,
                                   stats_data=body)
        if error:
            return json_error(400, error)
        return json_response(201, watch_data)

    def list_watch_data(self, req, watch_name):
        con = context.get_admin_context()
        data = self.engine_rpcapi.list_watch_data(con,
                    watch_name=watch_name)
        if data:
            return data
        else:
            return json_error(404,
                              'The watch "%s" does not exist.' % watch_name)


def create_resource(options):
    """
    Stacks resource factory method.
    """
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(MetadataController(options), deserializer, serializer)
