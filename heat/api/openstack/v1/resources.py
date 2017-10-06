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

import itertools

import six
from webob import exc

from heat.api.openstack.v1 import util
from heat.common.i18n import _
from heat.common import identifier
from heat.common import param_utils
from heat.common import serializers
from heat.common import wsgi
from heat.rpc import api as rpc_api
from heat.rpc import client as rpc_client


def format_resource(req, res, keys=None):
    keys = keys or []

    def include_key(k):
        return k in keys if keys else True

    def transform(key, value):
        if not include_key(key):
            return

        if key == rpc_api.RES_ID:
            identity = identifier.ResourceIdentifier(**value)
            links = [util.make_link(req, identity),
                     util.make_link(req, identity.stack(), 'stack')]

            nested_id = res.get(rpc_api.RES_NESTED_STACK_ID)
            if nested_id:
                nested_identity = identifier.HeatIdentifier(**nested_id)
                links.append(util.make_link(req, nested_identity, 'nested'))

            yield ('links', links)
        elif (key == rpc_api.RES_STACK_NAME or
              key == rpc_api.RES_STACK_ID or
              key == rpc_api.RES_ACTION or
              key == rpc_api.RES_NESTED_STACK_ID):
            return
        elif (key == rpc_api.RES_METADATA):
            return
        elif (key == rpc_api.RES_STATUS and rpc_api.RES_ACTION in res):
            # To avoid breaking API compatibility, we join RES_ACTION
            # and RES_STATUS, so the API format doesn't expose the
            # internal split of state into action/status
            yield (key, '_'.join((res[rpc_api.RES_ACTION], value)))
        elif (key == rpc_api.RES_NAME):
            yield ('logical_resource_id', value)
            yield (key, value)

        else:
            yield (key, value)

    return dict(itertools.chain.from_iterable(
        transform(k, v) for k, v in res.items()))


class ResourceController(object):
    """WSGI controller for Resources in Heat v1 API.

    Implements the API actions.
    """
    # Define request scope (must match what is in policy.json or policies in
    # code)
    REQUEST_SCOPE = 'resource'

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    def _extract_to_param(self, req, rpc_param, extractor, default):
        key = rpc_param
        if key in req.params:
            try:
                return extractor(key, req.params[key])
            except ValueError as e:
                raise exc.HTTPBadRequest(six.text_type(e))
        else:
            return default

    @util.registered_identified_stack
    def index(self, req, identity):
        """Lists information for all resources."""

        whitelist = {
            'type': 'mixed',
            'status': 'mixed',
            'name': 'mixed',
            'action': 'mixed',
            'id': 'mixed',
            'physical_resource_id': 'mixed'
        }

        invalid_keys = (set(req.params.keys()) -
                        set(list(whitelist) + [rpc_api.PARAM_NESTED_DEPTH,
                                               rpc_api.PARAM_WITH_DETAIL]))
        if invalid_keys:
            raise exc.HTTPBadRequest(_('Invalid filter parameters %s') %
                                     six.text_type(list(invalid_keys)))

        nested_depth = self._extract_to_param(req,
                                              rpc_api.PARAM_NESTED_DEPTH,
                                              param_utils.extract_int,
                                              default=0)
        with_detail = self._extract_to_param(req,
                                             rpc_api.PARAM_WITH_DETAIL,
                                             param_utils.extract_bool,
                                             default=False)

        params = util.get_allowed_params(req.params, whitelist)

        res_list = self.rpc_client.list_stack_resources(req.context,
                                                        identity,
                                                        nested_depth,
                                                        with_detail,
                                                        filters=params)

        return {'resources': [format_resource(req, res) for res in res_list]}

    @util.registered_identified_stack
    def show(self, req, identity, resource_name):
        """Gets detailed information for a resource."""

        whitelist = {'with_attr': util.PARAM_TYPE_MULTI}
        params = util.get_allowed_params(req.params, whitelist)
        if 'with_attr' not in params:
            params['with_attr'] = None
        res = self.rpc_client.describe_stack_resource(req.context,
                                                      identity,
                                                      resource_name,
                                                      **params)

        return {'resource': format_resource(req, res)}

    @util.registered_identified_stack
    def metadata(self, req, identity, resource_name):
        """Gets metadata information for a resource."""

        res = self.rpc_client.describe_stack_resource(req.context,
                                                      identity,
                                                      resource_name)

        return {rpc_api.RES_METADATA: res[rpc_api.RES_METADATA]}

    @util.registered_identified_stack
    def signal(self, req, identity, resource_name, body=None):
        self.rpc_client.resource_signal(req.context,
                                        stack_identity=identity,
                                        resource_name=resource_name,
                                        details=body)

    @util.registered_identified_stack
    def mark_unhealthy(self, req, identity, resource_name, body):
        """Mark a resource as healthy or unhealthy."""
        data = dict()
        VALID_KEYS = (RES_UPDATE_MARK_UNHEALTHY, RES_UPDATE_STATUS_REASON) = (
            'mark_unhealthy', rpc_api.RES_STATUS_DATA)

        invalid_keys = set(body) - set(VALID_KEYS)
        if invalid_keys:
            raise exc.HTTPBadRequest(_("Invalid keys in resource "
                                       "mark unhealthy %s") % invalid_keys)

        if RES_UPDATE_MARK_UNHEALTHY not in body:
            raise exc.HTTPBadRequest(
                _("Missing mandatory (%s) key from mark unhealthy "
                  "request") % RES_UPDATE_MARK_UNHEALTHY)

        try:
            data[RES_UPDATE_MARK_UNHEALTHY] = param_utils.extract_bool(
                RES_UPDATE_MARK_UNHEALTHY,
                body[RES_UPDATE_MARK_UNHEALTHY])
        except ValueError as e:
            raise exc.HTTPBadRequest(six.text_type(e))

        data[RES_UPDATE_STATUS_REASON] = body.get(RES_UPDATE_STATUS_REASON, "")
        self.rpc_client.resource_mark_unhealthy(req.context,
                                                stack_identity=identity,
                                                resource_name=resource_name,
                                                **data)


def create_resource(options):
    """Resources resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(ResourceController(options), deserializer, serializer)
