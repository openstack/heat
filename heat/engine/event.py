
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

from heat.db import api as db_api
from heat.common import exception
from heat.common import identifier
from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _

logger = logging.getLogger(__name__)


class Event(object):
    '''Class representing a Resource state change.'''

    def __init__(self, context, stack, action, status, reason,
                 physical_resource_id, resource_properties, resource_name,
                 resource_type, uuid=None, timestamp=None, id=None):
        '''
        Initialise from a context, stack, and event information. The timestamp
        and database ID may also be initialised if the event is already in the
        database.
        '''
        self.context = context
        self.stack = stack
        self.action = action
        self.status = status
        self.reason = reason
        self.physical_resource_id = physical_resource_id
        self.resource_name = resource_name
        self.resource_type = resource_type
        try:
            self.resource_properties = dict(resource_properties)
        except ValueError as ex:
            self.resource_properties = {'Error': str(ex)}
        self.uuid = uuid
        self.timestamp = timestamp
        self.id = id

    @classmethod
    def load(cls, context, event_id, event=None, stack=None):
        '''Retrieve an Event from the database.'''
        from heat.engine import parser

        ev = event if event is not None else\
            db_api.event_get(context, event_id)
        if ev is None:
            message = _('No event exists with id "%s"') % str(event_id)
            raise exception.NotFound(message)

        st = stack if stack is not None else\
            parser.Stack.load(context, ev.stack_id)

        return cls(context, st, ev.resource_action, ev.resource_status,
                   ev.resource_status_reason, ev.physical_resource_id,
                   ev.resource_properties, ev.resource_name,
                   ev.resource_type, ev.uuid, ev.created_at, ev.id)

    def store(self):
        '''Store the Event in the database.'''
        ev = {
            'resource_name': self.resource_name,
            'physical_resource_id': self.physical_resource_id,
            'stack_id': self.stack.id,
            'resource_action': self.action,
            'resource_status': self.status,
            'resource_status_reason': self.reason,
            'resource_type': self.resource_type,
            'resource_properties': self.resource_properties,
        }

        if self.uuid is not None:
            ev['uuid'] = self.uuid

        if self.timestamp is not None:
            ev['created_at'] = self.timestamp

        if self.id is not None:
            logger.warning(_('Duplicating event'))

        new_ev = db_api.event_create(self.context, ev)
        self.id = new_ev.id
        return self.id

    def identifier(self):
        '''Return a unique identifier for the event.'''
        if self.uuid is None:
            return None

        res_id = identifier.ResourceIdentifier(
            resource_name=self.resource_name, **self.stack.identifier())

        return identifier.EventIdentifier(event_id=str(self.uuid), **res_id)
