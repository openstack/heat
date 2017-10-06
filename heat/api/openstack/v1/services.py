# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_messaging import exceptions
from webob import exc

from heat.api.openstack.v1 import util
from heat.common.i18n import _
from heat.common import serializers
from heat.common import wsgi
from heat.rpc import client as rpc_client


class ServiceController(object):
    """WSGI controller for reporting the heat engine status in Heat v1 API."""
    # Define request scope (must match what is in policy.json or policies in
    # code)
    REQUEST_SCOPE = 'service'

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    @util.registered_policy_enforce
    def index(self, req):
        try:
            services = self.rpc_client.list_services(req.context)
            return {'services': services}
        except exceptions.MessagingTimeout:
            msg = _('All heat engines are down.')
            raise exc.HTTPServiceUnavailable(msg)


def create_resource(options):
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(ServiceController(options), deserializer, serializer)
