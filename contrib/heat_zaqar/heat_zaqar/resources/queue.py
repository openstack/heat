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

from heat.common import exception
from heat.engine import attributes
from heat.engine import clients
from heat.engine import properties
from heat.engine import resource


def resource_mapping():
    if not clients.has_client('zaqar'):
        return {}
    return {
        'OS::Zaqar::Queue': ZaqarQueue,
    }


class ZaqarQueue(resource.Resource):

    PROPERTIES = (
        NAME, METADATA,
    ) = (
        'name', 'metadata',
    )

    ATTRIBUTES = (
        QUEUE_ID, HREF,
    ) = (
        'queue_id', 'href',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _("Name of the queue instance to create."),
            required=True),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            description=_("Arbitrary key/value metadata to store "
                          "contextual information about this queue."),
            update_allowed=True)
    }

    attributes_schema = {
        QUEUE_ID: attributes.Schema(
            _("ID of the queue."),
            cache_mode=attributes.Schema.CACHE_NONE
        ),
        HREF: attributes.Schema(
            _("The resource href of the queue.")
        ),
    }

    def zaqar(self):
        return self.clients.client('zaqar')

    def physical_resource_name(self):
        return self.properties[self.NAME]

    def handle_create(self):
        """Create a zaqar message queue."""
        queue_name = self.physical_resource_name()
        queue = self.zaqar().queue(queue_name, auto_create=False)
        # Zaqar client doesn't report an error if an queue with the same
        # id/name already exists, which can cause issue with stack update.
        if queue.exists():
            raise exception.Error(_('Message queue %s already exists.')
                                  % queue_name)
        queue.ensure_exists()
        self.resource_id_set(queue_name)
        return queue

    def check_create_complete(self, queue):
        """Set metadata of the newly created queue."""
        if queue.exists():
            metadata = self.properties.get('metadata')
            if metadata:
                queue.metadata(new_meta=metadata)
            return True

        queue_name = self.physical_resource_name()
        raise exception.Error(_('Message queue %s creation failed.')
                              % queue_name)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Update queue metadata."""
        if 'metadata' in prop_diff:
            queue = self.zaqar().queue(self.resource_id, auto_create=False)
            metadata = prop_diff['metadata']
            queue.metadata(new_meta=metadata)

    def handle_delete(self):
        """Delete a zaqar message queue."""
        if not self.resource_id:
            return

        queue = self.zaqar().queue(self.resource_id, auto_create=False)
        queue.delete()

    def href(self):
        api_endpoint = self.zaqar().api_url
        queue_name = self.physical_resource_name()
        if api_endpoint.endswith('/'):
            return '%squeues/%s' % (api_endpoint, queue_name)
        else:
            return '%s/queues/%s' % (api_endpoint, queue_name)

    def _resolve_attribute(self, name):
        if name == self.QUEUE_ID:
            return self.resource_id
        elif name == self.HREF:
            return self.href()
