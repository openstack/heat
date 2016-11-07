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

from oslo_serialization import jsonutils

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class ZaqarQueue(resource.Resource):
    """A resource for managing Zaqar queues.

    Queue is a logical entity that groups messages. Ideally a queue is created
    per work type. For example, if you want to compress files, you would create
    a queue dedicated for this job. Any application that reads from this queue
    would only compress files.
    """

    default_client_name = "zaqar"

    support_status = support.SupportStatus(version='2014.2')

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
            cache_mode=attributes.Schema.CACHE_NONE,
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='6.0.0',
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    message=_("Use get_resource|Ref command instead. "
                              "For example: { get_resource : "
                              "<resource_name> }"),
                    version='2015.1',
                    previous_status=support.SupportStatus(version='2014.1')
                )
            )
        ),
        HREF: attributes.Schema(
            _("The resource href of the queue.")
        ),
    }

    def physical_resource_name(self):
        return self.properties[self.NAME]

    def handle_create(self):
        """Create a zaqar message queue."""
        queue_name = self.physical_resource_name()
        queue = self.client().queue(queue_name, auto_create=False)
        metadata = self.properties.get('metadata')
        if metadata:
            queue.metadata(new_meta=metadata)
        self.resource_id_set(queue_name)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Update queue metadata."""
        if 'metadata' in prop_diff:
            queue = self.client().queue(self.resource_id, auto_create=False)
            metadata = prop_diff['metadata']
            queue.metadata(new_meta=metadata)

    def handle_delete(self):
        """Delete a zaqar message queue."""
        if not self.resource_id:
            return
        with self.client_plugin().ignore_not_found:
            self.client().queue(self.resource_id, auto_create=False).delete()

    def href(self):
        api_endpoint = self.client().api_url
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

    def _show_resource(self):
        queue = self.client().queue(self.resource_id, auto_create=False)
        metadata = queue.metadata()
        return {self.METADATA: metadata}

    def parse_live_resource_data(self, resource_properties, resource_data):
        return {
            self.NAME: self.resource_id,
            self.METADATA: resource_data[self.METADATA]
        }


class ZaqarSignedQueueURL(resource.Resource):
    """A resource for managing signed URLs of Zaqar queues.

    Signed URLs allow to give specific access to queues, for example to be used
    as alarm notifications.
    """

    default_client_name = "zaqar"

    support_status = support.SupportStatus(version='8.0.0')

    PROPERTIES = (
        QUEUE, PATHS, TTL, METHODS,
    ) = (
        'queue', 'paths', 'ttl', 'methods',
    )

    ATTRIBUTES = (
        SIGNATURE, EXPIRES, PATHS_ATTR, METHODS_ATTR,
    ) = (
        'signature', 'expires', 'paths', 'methods',
    )

    properties_schema = {
        QUEUE: properties.Schema(
            properties.Schema.STRING,
            _("Name of the queue instance to create a URL for."),
            required=True),
        PATHS: properties.Schema(
            properties.Schema.LIST,
            description=_("List of allowed paths to be accessed. "
                          "Default to allow queue messages URL.")),
        TTL: properties.Schema(
            properties.Schema.INTEGER,
            description=_("Time validity of the URL, in seconds. "
                          "Default to one day.")),
        METHODS: properties.Schema(
            properties.Schema.LIST,
            description=_("List of allowed HTTP methods to be used. "
                          "Default to allow GET."),
            schema=properties.Schema(
                properties.Schema.STRING,
                constraints=[
                    constraints.AllowedValues(['GET', 'DELETE', 'PATCH',
                                               'POST', 'PUT']),
                ],
            ))
    }

    attributes_schema = {
        SIGNATURE: attributes.Schema(
            _("Signature of the URL built by Zaqar.")
        ),
        EXPIRES: attributes.Schema(
            _("Expiration date of the URL.")
        ),
        PATHS_ATTR: attributes.Schema(
            _("Comma-delimited list of paths for convenience.")
        ),
        METHODS_ATTR: attributes.Schema(
            _("Comma-delimited list of methods for convenience.")
        ),
    }

    def handle_create(self):
        queue = self.client().queue(self.properties[self.QUEUE])
        signed_url = queue.signed_url(paths=self.properties[self.PATHS],
                                      methods=self.properties[self.METHODS],
                                      ttl_seconds=self.properties[self.TTL])
        self.data_set(self.SIGNATURE, signed_url['signature'])
        self.data_set(self.EXPIRES, signed_url['expires'])
        self.data_set(self.PATHS, jsonutils.dumps(signed_url['paths']))
        self.data_set(self.METHODS, jsonutils.dumps(signed_url['methods']))
        self.resource_id_set(self._url(signed_url))

    def _url(self, data):
        """Return a URL that can be used for example for alarming."""
        return ('zaqar://?signature={0}&expires={1}&paths={2}'
                '&methods={3}&project_id={4}&queue_name={5}'.format(
                    data['signature'], data['expires'],
                    ','.join(data['paths']), ','.join(data['methods']),
                    data['project'], self.properties[self.QUEUE]))

    def handle_delete(self):
        # We can't delete a signed URL
        return True

    def _resolve_attribute(self, name):
        if not self.resource_id:
            return
        if name == self.SIGNATURE:
            return self.data()[self.SIGNATURE]
        elif name == self.EXPIRES:
            return self.data()[self.EXPIRES]
        elif name == self.PATHS:
            return jsonutils.loads(self.data()[self.PATHS])
        elif name == self.METHODS:
            return jsonutils.loads(self.data()[self.METHODS])


def resource_mapping():
    return {
        'OS::Zaqar::Queue': ZaqarQueue,
        'OS::Zaqar::SignedQueueURL': ZaqarSignedQueueURL,
    }
