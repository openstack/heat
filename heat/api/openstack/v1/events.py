
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

from webob import exc

from heat.api.openstack.v1 import util
from heat.common import identifier
from heat.common import wsgi
from heat.rpc import api as engine_api
from heat.rpc import client as rpc_client


summary_keys = [
    engine_api.EVENT_ID,
    engine_api.EVENT_TIMESTAMP,
    engine_api.EVENT_RES_NAME,
    engine_api.EVENT_RES_STATUS,
    engine_api.EVENT_RES_STATUS_DATA,
    engine_api.EVENT_RES_PHYSICAL_ID,
]


def format_event(req, event, keys=None):
    include_key = lambda k: k in keys if keys else True

    def transform(key, value):
        if not include_key(key):
            return

        if key == engine_api.EVENT_ID:
            identity = identifier.EventIdentifier(**value)
            yield ('id', identity.event_id)
            yield ('links', [util.make_link(req, identity),
                             util.make_link(req, identity.resource(),
                                            'resource'),
                             util.make_link(req, identity.stack(),
                                            'stack')])
        elif key in (engine_api.EVENT_STACK_ID, engine_api.EVENT_STACK_NAME,
                     engine_api.EVENT_RES_ACTION):
            return
        elif (key == engine_api.EVENT_RES_STATUS and
              engine_api.EVENT_RES_ACTION in event):
            # To avoid breaking API compatibility, we join RES_ACTION
            # and RES_STATUS, so the API format doesn't expose the
            # internal split of state into action/status
            yield (key, '_'.join((event[engine_api.EVENT_RES_ACTION], value)))
        elif (key == engine_api.RES_NAME):
            yield ('logical_resource_id', value)
            yield (key, value)

        else:
            yield (key, value)

    return dict(itertools.chain.from_iterable(
        transform(k, v) for k, v in event.items()))


class EventController(object):
    """
    WSGI controller for Events in Heat v1 API
    Implements the API actions
    """
    # Define request scope (must match what is in policy.json)
    REQUEST_SCOPE = 'events'

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    def _event_list(self, req, identity,
                    filter_func=lambda e: True, detail=False):
        events = self.rpc_client.list_events(req.context,
                                             identity)
        keys = None if detail else summary_keys

        return [format_event(req, e, keys) for e in events if filter_func(e)]

    @util.identified_stack
    def index(self, req, identity, resource_name=None):
        """
        Lists summary information for all events
        """

        if resource_name is None:
            events = self._event_list(req, identity)
        else:
            res_match = lambda e: e[engine_api.EVENT_RES_NAME] == resource_name

            events = self._event_list(req, identity, res_match)
            if not events:
                msg = _('No events found for resource %s') % resource_name
                raise exc.HTTPNotFound(msg)

        return {'events': events}

    @util.identified_stack
    def show(self, req, identity, resource_name, event_id):
        """
        Gets detailed information for an event
        """

        def event_match(ev):
            identity = identifier.EventIdentifier(**ev[engine_api.EVENT_ID])
            return (ev[engine_api.EVENT_RES_NAME] == resource_name and
                    identity.event_id == event_id)

        events = self._event_list(req, identity, event_match, True)
        if not events:
            raise exc.HTTPNotFound(_('No event %s found') % event_id)

        return {'event': events[0]}


def create_resource(options):
    """
    Events resource factory method.
    """
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(EventController(options), deserializer, serializer)
