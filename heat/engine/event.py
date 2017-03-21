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

from heat.common import identifier
from heat.objects import event as event_object


class Event(object):
    """Class representing a Resource state change."""

    def __init__(self, context, stack, action, status, reason,
                 physical_resource_id, resource_prop_data_id,
                 resource_properties, resource_name,
                 resource_type, uuid=None, timestamp=None, id=None):
        """Initialise from a context, stack, and event information.

        The timestamp and database ID may also be initialised if the event is
        already in the database.
        """
        self.context = context
        self._stack_identifier = stack.identifier()
        self.action = action
        self.status = status
        self.reason = reason
        self.physical_resource_id = physical_resource_id
        self.resource_name = resource_name
        self.resource_type = resource_type
        self.rsrc_prop_data_id = resource_prop_data_id
        self.resource_properties = resource_properties
        if self.resource_properties is None:
            self.resource_properties = {}
        self.uuid = uuid
        self.timestamp = timestamp
        self.id = id

    def store(self):
        """Store the Event in the database."""
        ev = {
            'resource_name': self.resource_name,
            'physical_resource_id': self.physical_resource_id,
            'stack_id': self._stack_identifier.stack_id,
            'resource_action': self.action,
            'resource_status': self.status,
            'resource_status_reason': self.reason,
            'resource_type': self.resource_type,
        }

        if self.uuid is not None:
            ev['uuid'] = self.uuid

        if self.timestamp is not None:
            ev['created_at'] = self.timestamp

        if self.rsrc_prop_data_id is not None:
            ev['rsrc_prop_data_id'] = self.rsrc_prop_data_id

        new_ev = event_object.Event.create(self.context, ev)

        self.id = new_ev.id
        self.timestamp = new_ev.created_at
        self.uuid = new_ev.uuid
        return self.id

    def identifier(self):
        """Return a unique identifier for the event."""
        if self.uuid is None:
            return None

        res_id = identifier.ResourceIdentifier(
            resource_name=self.resource_name, **self._stack_identifier)

        return identifier.EventIdentifier(event_id=str(self.uuid), **res_id)

    def as_dict(self):
        return {
            'timestamp': self.timestamp.isoformat(),
            'version': '0.1',
            'type': 'os.heat.event',
            'id': self.uuid,
            'payload': {
                'resource_name': self.resource_name,
                'physical_resource_id': self.physical_resource_id,
                'stack_id': self._stack_identifier.stack_id,
                'resource_action': self.action,
                'resource_status': self.status,
                'resource_status_reason': self.reason,
                'resource_type': self.resource_type,
                'resource_properties': self.resource_properties,
                'version': '0.1'
            }
        }
