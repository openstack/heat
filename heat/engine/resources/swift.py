# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from urlparse import urlparse

from heat.common import exception
from heat.engine import resource
from heat.openstack.common import log as logging
from heat.engine import clients

logger = logging.getLogger(__name__)


class SwiftContainer(resource.Resource):
    properties_schema = {
        'name': {'Type': 'String'},
        'X-Container-Read': {'Type': 'String'},
        'X-Container-Write': {'Type': 'String'},
        'X-Container-Meta': {'Type': 'Map', 'Default': {}}}

    def validate(self):
        '''
        Validate any of the provided params
        '''
        #check if swiftclient is installed
        if clients.swiftclient is None:
            return {'Error':
                    'SwiftContainer unavailable due to missing swiftclient.'}

    def physical_resource_name(self):
        name = self.properties.get('name')
        if name:
            return name

        return super(SwiftContainer, self).physical_resource_name()

    @staticmethod
    def _build_meta_headers(meta_props):
        '''
        Returns a new dict where each key is prepended with:
        X-Container-Meta-
        '''
        if meta_props is None:
            return {}
        return dict(
            ('X-Container-Meta-' + k, v) for (k, v) in meta_props.items())

    def handle_create(self):
        """Create a container."""
        container = self.physical_resource_name()
        headers = SwiftContainer._build_meta_headers(
            self.properties['X-Container-Meta'])
        if 'X-Container-Read' in self.properties.keys():
            headers['X-Container-Read'] = self.properties['X-Container-Read']
        if 'X-Container-Write' in self.properties.keys():
            headers['X-Container-Write'] = self.properties['X-Container-Write']
        logger.debug('SwiftContainer create container %s with headers %s' %
                     (container, headers))

        self.swift().put_container(container, headers)
        self.resource_id_set(container)

    def handle_delete(self):
        """Perform specified delete policy."""
        logger.debug('SwiftContainer delete container %s' % self.resource_id)
        if self.resource_id is not None:
            try:
                self.swift().delete_container(self.resource_id)
            except clients.swiftclient.ClientException as ex:
                logger.warn("Delete container failed: %s" % str(ex))

    def FnGetRefId(self):
        return unicode(self.resource_id)

    def FnGetAtt(self, key):
        url, token_id = self.swift().get_auth()
        parsed = list(urlparse(url))
        if key == 'DomainName':
            return parsed[1].split(':')[0]
        elif key == 'WebsiteURL':
            return '%s://%s%s/%s' % (parsed[0], parsed[1], parsed[2],
                                     self.resource_id)
        elif key == 'RootURL':
            return '%s://%s%s' % (parsed[0], parsed[1], parsed[2])
        elif self.resource_id and key in (
                'ObjectCount', 'BytesUsed', 'HeadContainer'):
            try:
                headers = self.swift().head_container(self.resource_id)
            except clients.swiftclient.ClientException as ex:
                logger.warn("Head container failed: %s" % str(ex))
                return None
            else:
                if key == 'ObjectCount':
                    return headers['x-container-object-count']
                elif key == 'BytesUsed':
                    return headers['x-container-bytes-used']
                elif key == 'HeadContainer':
                    return headers
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)


def resource_mapping():
    if clients.swiftclient is None:
        return {}

    return {
        'OS::Swift::Container': SwiftContainer,
    }
