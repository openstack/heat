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
from heat.common import short_id
from heat.openstack.common import log as logging
from heat.engine import clients

logger = logging.getLogger(__name__)


class S3Bucket(resource.Resource):
    website_schema = {'IndexDocument': {'Type': 'String'},
                      'ErrorDocument': {'Type': 'String'}}
    properties_schema = {'AccessControl': {
                         'Type': 'String',
                         'AllowedValues': ['Private',
                                           'PublicRead',
                                           'PublicReadWrite',
                                           'AuthenticatedRead',
                                           'BucketOwnerRead',
                                           'BucketOwnerFullControl']},
                         'WebsiteConfiguration': {'Type': 'Map',
                                                  'Schema': website_schema}}

    def __init__(self, name, json_snippet, stack):
        super(S3Bucket, self).__init__(name, json_snippet, stack)

    def validate(self):
        '''
        Validate any of the provided params
        '''
        #check if swiftclient is installed
        if clients.swiftclient is None:
            return {'Error':
                    'S3 services unavailable because of missing swiftclient.'}

    def _create_container_name(self):
        return '%s-%s-%s' % (self.stack.name, self.name,
                             short_id.generate_id())

    def handle_create(self):
        """Create a bucket."""
        container = self._create_container_name()
        headers = {}
        logger.debug('S3Bucket create container %s with headers %s' %
                     (container, headers))
        if self.properties['WebsiteConfiguration'] is not None:
            sc = self.properties['WebsiteConfiguration']
            # we will assume that swift is configured for the staticweb
            # wsgi middleware
            headers['X-Container-Meta-Web-Index'] = sc['IndexDocument']
            headers['X-Container-Meta-Web-Error'] = sc['ErrorDocument']

        con = self.context
        ac = self.properties['AccessControl']
        tenant_username = '%s:%s' % (con.tenant, con.username)
        if ac in ('PublicRead', 'PublicReadWrite'):
            headers['X-Container-Read'] = '.r:*'
        elif ac == 'AuthenticatedRead':
            headers['X-Container-Read'] = con.tenant
        else:
            headers['X-Container-Read'] = tenant_username

        if ac == 'PublicReadWrite':
            headers['X-Container-Write'] = '.r:*'
        else:
            headers['X-Container-Write'] = tenant_username

        self.swift().put_container(container, headers)
        self.resource_id_set(container)

    def handle_update(self, json_snippet):
        return self.UPDATE_REPLACE

    def handle_delete(self):
        """Perform specified delete policy"""
        logger.debug('S3Bucket delete container %s' % self.resource_id)
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
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)


def resource_mapping():
    if clients.swiftclient is None:
        return {}

    return {
        'AWS::S3::Bucket': S3Bucket,
    }
