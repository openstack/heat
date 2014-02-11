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
from heat.engine import clients
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common import log as logging


logger = logging.getLogger(__name__)


try:
    from marconiclient.queues.v1 import client as marconiclient
except ImportError:
    marconiclient = None
    logger.info(_('marconiclient not available'))

    def resource_mapping():
        return {}
else:
    def resource_mapping():
        return {
            'OS::Marconi::Queue': MarconiQueue,
        }


class Clients(clients.OpenStackClients):
    '''
    Convenience class to create and cache client instances.
    '''
    def __init__(self, context):
        super(Clients, self).__init__(context)
        self._marconi = None

    def marconi(self, service_type="queuing"):
        if self._marconi:
            return self._marconi

        con = self.context
        if self.auth_token is None:
            logger.error(_("Marconi connection failed, no auth_token!"))
            return None

        opts = {
            'os_auth_token': con.auth_token,
            'os_auth_url': con.auth_url,
            'os_project_id': con.tenant,
            'os_service_type': service_type,
        }
        auth_opts = {'backend': 'keystone',
                     'options': opts}
        conf = {'auth_opts': auth_opts}
        endpoint = self.url_for(service_type=service_type)

        self._marconi = marconiclient.Client(url=endpoint, conf=conf)

        return self._marconi


class MarconiQueue(resource.Resource):

    PROPERTIES = (
        NAME, METADATA,
    ) = (
        'name', 'metadata',
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
        "queue_id": _("ID of the queue."),
        "href": _("The resource href of the queue.")
    }

    update_allowed_keys = ('Properties',)

    def __init__(self, name, json_snippet, stack):
        super(MarconiQueue, self).__init__(name, json_snippet, stack)
        self.clients = Clients(self.context)

    def marconi(self):
        return self.clients.marconi()

    def physical_resource_name(self):
        return self.properties[self.NAME]

    def handle_create(self):
        '''
        Create a marconi message queue.
        '''
        queue_name = self.physical_resource_name()
        queue = self.marconi().queue(queue_name, auto_create=False)
        # Marconi client doesn't report an error if an queue with the same
        # id/name already exists, which can cause issue with stack update.
        if queue.exists():
            raise exception.Error(_('Message queue %s already exists.')
                                  % queue_name)
        queue.ensure_exists()
        self.resource_id_set(queue_name)
        return queue

    def check_create_complete(self, queue):
        # set metadata of the newly created queue
        if queue.exists():
            metadata = self.properties.get('metadata')
            if metadata:
                queue.metadata(new_meta=metadata)
            return True

        queue_name = self.physical_resource_name()
        raise exception.Error(_('Message queue %s creation failed.')
                              % queue_name)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        '''
        Update queue metadata.
        '''
        if 'metadata' in prop_diff:
            queue = self.marconi().queue(self.resource_id, auto_create=False)
            metadata = prop_diff['metadata']
            queue.metadata(new_meta=metadata)

    def handle_delete(self):
        '''
        Delete a marconi message queue.
        '''
        if not self.resource_id:
            return

        queue = self.marconi().queue(self.resource_id, auto_create=False)
        queue.delete()

    def href(self):
        api_endpoint = self.marconi().api_url
        queue_name = self.physical_resource_name()
        if api_endpoint.endswith('/'):
            return '%squeues/%s' % (api_endpoint, queue_name)
        else:
            return '%s/queues/%s' % (api_endpoint, queue_name)

    def _resolve_attribute(self, name):
        if name == 'queue_id':
            return self.resource_id
        elif name == 'href':
            return self.href()
