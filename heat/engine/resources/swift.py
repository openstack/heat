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

from six.moves.urllib import parse as urlparse
from swiftclient import exceptions as swift_exceptions

from heat.common import exception
from heat.engine import attributes
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class SwiftContainer(resource.Resource):
    PROPERTIES = (
        NAME, X_CONTAINER_READ, X_CONTAINER_WRITE, X_CONTAINER_META,
        X_ACCOUNT_META
    ) = (
        'name', 'X-Container-Read', 'X-Container-Write', 'X-Container-Meta',
        'X-Account-Meta'
    )

    ATTRIBUTES = (
        DOMAIN_NAME, WEBSITE_URL, ROOT_URL, OBJECT_COUNT, BYTES_USED,
        HEAD_CONTAINER,
    ) = (
        'DomainName', 'WebsiteURL', 'RootURL', 'ObjectCount', 'BytesUsed',
        'HeadContainer',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the container. If not specified, a unique name will '
              'be generated.')
        ),
        X_CONTAINER_READ: properties.Schema(
            properties.Schema.STRING,
            _('Specify the ACL permissions on who can read objects in the '
              'container.')
        ),
        X_CONTAINER_WRITE: properties.Schema(
            properties.Schema.STRING,
            _('Specify the ACL permissions on who can write objects to the '
              'container.')
        ),
        X_CONTAINER_META: properties.Schema(
            properties.Schema.MAP,
            _('A map of user-defined meta data to associate with the '
              'container. Each key in the map will set the header '
              'X-Container-Meta-{key} with the corresponding value.'),
            default={}
        ),
        X_ACCOUNT_META: properties.Schema(
            properties.Schema.MAP,
            _('A map of user-defined meta data to associate with the '
              'account. Each key in the map will set the header '
              'X-Account-Meta-{key} with the corresponding value.'),
            default={}
        ),
    }

    attributes_schema = {
        DOMAIN_NAME: attributes.Schema(
            _('The host from the container URL.')
        ),
        WEBSITE_URL: attributes.Schema(
            _('The URL of the container.')
        ),
        ROOT_URL: attributes.Schema(
            _('The parent URL of the container.')
        ),
        OBJECT_COUNT: attributes.Schema(
            _('The number of objects stored in the container.')
        ),
        BYTES_USED: attributes.Schema(
            _('The number of bytes stored in the container.')
        ),
        HEAD_CONTAINER: attributes.Schema(
            _('A map containing all headers for the container.')
        ),
    }

    def physical_resource_name(self):
        name = self.properties.get(self.NAME)
        if name:
            return name

        return super(SwiftContainer, self).physical_resource_name()

    @staticmethod
    def _build_meta_headers(obj_type, meta_props):
        '''
        Returns a new dict where each key is prepended with:
        X-Container-Meta-
        '''
        if meta_props is None:
            return {}
        return dict(
            ('X-' + obj_type.title() + '-Meta-' + k, v)
            for (k, v) in meta_props.items())

    def handle_create(self):
        """Create a container."""
        container = self.physical_resource_name()

        container_headers = SwiftContainer._build_meta_headers(
            "container", self.properties[self.X_CONTAINER_META])

        account_headers = SwiftContainer._build_meta_headers(
            "account", self.properties[self.X_ACCOUNT_META])

        for key in (self.X_CONTAINER_READ, self.X_CONTAINER_WRITE):
            if self.properties.get(key) is not None:
                container_headers[key] = self.properties[key]

        LOG.debug('SwiftContainer create container %(container)s with '
                  'container headers %(container_headers)s and '
                  'account headers %(account_headers)s'
                  % {'container': container,
                     'account_headers': account_headers,
                     'container_headers': container_headers})

        self.swift().put_container(container, container_headers)

        if account_headers:
            self.swift().post_account(account_headers)

        self.resource_id_set(container)

    def handle_delete(self):
        """Perform specified delete policy."""
        LOG.debug('SwiftContainer delete container %s' % self.resource_id)
        if self.resource_id is not None:
            try:
                self.swift().delete_container(self.resource_id)
            except swift_exceptions.ClientException as ex:
                LOG.warn(_("Delete container failed: %s") % ex)

    def FnGetRefId(self):
        return unicode(self.resource_id)

    def FnGetAtt(self, key):
        parsed = list(urlparse.urlparse(self.swift().url))
        if key == self.DOMAIN_NAME:
            return parsed[1].split(':')[0]
        elif key == self.WEBSITE_URL:
            return '%s://%s%s/%s' % (parsed[0], parsed[1], parsed[2],
                                     self.resource_id)
        elif key == self.ROOT_URL:
            return '%s://%s%s' % (parsed[0], parsed[1], parsed[2])
        elif self.resource_id and key in (
                self.OBJECT_COUNT, self.BYTES_USED, self.HEAD_CONTAINER):
            try:
                headers = self.swift().head_container(self.resource_id)
            except swift_exceptions.ClientException as ex:
                LOG.warn(_("Head container failed: %s") % ex)
                return None
            else:
                if key == self.OBJECT_COUNT:
                    return headers['x-container-object-count']
                elif key == self.BYTES_USED:
                    return headers['x-container-bytes-used']
                elif key == self.HEAD_CONTAINER:
                    return headers
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)


def resource_mapping():
    return {
        'OS::Swift::Container': SwiftContainer,
    }
