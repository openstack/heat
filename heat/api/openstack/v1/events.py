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


summary_keys = [
    rpc_api.EVENT_ID,
    rpc_api.EVENT_TIMESTAMP,
    rpc_api.EVENT_RES_NAME,
    rpc_api.EVENT_RES_STATUS,
    rpc_api.EVENT_RES_STATUS_DATA,
    rpc_api.EVENT_RES_PHYSICAL_ID,
]


def format_event(req, event, keys=None):

    def include_key(k):
        return k in keys if keys else True

    def transform(key, value):
        if not include_key(key):
            return

        if key == rpc_api.EVENT_ID:
            identity = identifier.EventIdentifier(**value)
            yield ('id', identity.event_id)
            yield ('links', [util.make_link(req, identity),
                             util.make_link(req, identity.resource(),
                                            'resource'),
                             util.make_link(req, identity.stack(),
                                            'stack')])
        elif key in (rpc_api.EVENT_STACK_ID, rpc_api.EVENT_STACK_NAME,
                     rpc_api.EVENT_RES_ACTION):
            return
        elif (key == rpc_api.EVENT_RES_STATUS and
              rpc_api.EVENT_RES_ACTION in event):
            # To avoid breaking API compatibility, we join RES_ACTION
            # and RES_STATUS, so the API format doesn't expose the
            # internal split of state into action/status
            yield (key, '_'.join((event[rpc_api.EVENT_RES_ACTION], value)))
        elif (key == rpc_api.RES_NAME):
            yield ('logical_resource_id', value)
            yield (key, value)

        else:
            yield (key, value)

    ev = dict(itertools.chain.from_iterable(
        transform(k, v) for k, v in event.items()))

    root_stack_id = event.get(rpc_api.EVENT_ROOT_STACK_ID)
    if root_stack_id:
        root_identifier = identifier.HeatIdentifier(**root_stack_id)
        ev['links'].append(util.make_link(req, root_identifier, 'root_stack'))
    return ev


class EventController(object):
    """WSGI controller for Events in Heat v1 API.

    Implements the API actions.
    """
    # Define request scope (must match what is in policy.json or policies in
    # code)
    REQUEST_SCOPE = 'events'

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    def _event_list(self, req, identity, detail=False, filters=None,
                    limit=None, marker=None, sort_keys=None, sort_dir=None,
                    nested_depth=None):
        events = self.rpc_client.list_events(req.context,
                                             identity,
                                             filters=filters,
                                             limit=limit,
                                             marker=marker,
                                             sort_keys=sort_keys,
                                             sort_dir=sort_dir,
                                             nested_depth=nested_depth)
        keys = None if detail else summary_keys

        return [format_event(req, e, keys) for e in events]

    @util.registered_identified_stack
    def index(self, req, identity, resource_name=None):
        """Lists summary information for all events."""
        whitelist = {
            'limit': util.PARAM_TYPE_SINGLE,
            'marker': util.PARAM_TYPE_SINGLE,
            'sort_dir': util.PARAM_TYPE_SINGLE,
            'sort_keys': util.PARAM_TYPE_MULTI,
            'nested_depth': util.PARAM_TYPE_SINGLE,
        }
        filter_whitelist = {
            'resource_status': util.PARAM_TYPE_MIXED,
            'resource_action': util.PARAM_TYPE_MIXED,
            'resource_name': util.PARAM_TYPE_MIXED,
            'resource_type': util.PARAM_TYPE_MIXED,
        }
        params = util.get_allowed_params(req.params, whitelist)
        filter_params = util.get_allowed_params(req.params, filter_whitelist)

        int_params = (rpc_api.PARAM_LIMIT, rpc_api.PARAM_NESTED_DEPTH)
        try:
            for key in int_params:
                if key in params:
                    params[key] = param_utils.extract_int(
                        key, params[key], allow_zero=True)
        except ValueError as e:
            raise exc.HTTPBadRequest(six.text_type(e))

        if resource_name is None:
            if not filter_params:
                filter_params = None
        else:
            filter_params['resource_name'] = resource_name

        events = self._event_list(
            req, identity, filters=filter_params, **params)

        if not events and resource_name is not None:
            msg = _('No events found for resource %s') % resource_name
            raise exc.HTTPNotFound(msg)

        return {'events': events}

    @util.registered_identified_stack
    def show(self, req, identity, resource_name, event_id):
        """Gets detailed information for an event."""

        filters = {"resource_name": resource_name, "uuid": event_id}
        events = self._event_list(req, identity, filters=filters, detail=True)
        if not events:
            raise exc.HTTPNotFound(_('No event %s found') % event_id)

        return {'event': events[0]}


def create_resource(options):
    """Events resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(EventController(options), deserializer, serializer)
