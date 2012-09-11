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

import binascii
import os
from urlparse import urlparse

from heat.common import exception
from heat.engine.resources import Resource
from heat.openstack.common import log as logging
from swiftclient.client import ClientException

logger = logging.getLogger('heat.engine.s3')


class S3Bucket(Resource):
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
                        'DeletionPolicy': {
                            'Type': 'String',
                            'AllowedValues': ['Delete',
                                              'Retain']},
                        'WebsiteConfiguration': {'Type': 'Map',
                                                 'Schema': website_schema}}

    def __init__(self, name, json_snippet, stack):
        super(S3Bucket, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        """Create a bucket."""
        container = 'heat-%s-%s' % (self.name,
                                    binascii.hexlify(os.urandom(10)))
        headers = {}
        logger.debug('S3Bucket create container %s with headers %s' %
                     (container, headers))
        if 'WebsiteConfiguration' in self.properties:
            site_cfg = self.properties['WebsiteConfiguration']
            # we will assume that swift is configured for the staticweb
            # wsgi middleware
            headers['X-Container-Meta-Web-Index'] = site_cfg['IndexDocument']
            headers['X-Container-Meta-Web-Error'] = site_cfg['ErrorDocument']

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
        self.instance_id_set(container)

    def handle_update(self):
        return self.UPDATE_REPLACE

    def handle_delete(self):
        """Perform specified delete policy"""
        if self.properties['DeletionPolicy'] == 'Retain':
            return
        logger.debug('S3Bucket delete container %s' % self.instance_id)
        if self.instance_id is not None:
            try:
                self.swift().delete_container(self.instance_id)
            except ClientException as ex:
                logger.warn("Delete container failed: %s" % str(ex))

    def FnGetRefId(self):
        return unicode(self.instance_id)

    def FnGetAtt(self, key):
        url, token_id = self.swift().get_auth()
        parsed = list(urlparse(url))
        if key == 'DomainName':
            return parsed[1].split(':')[0]
        elif key == 'WebsiteURL':
            return '%s://%s%s/%s' % (parsed[0], parsed[1], parsed[2],
                                      self.instance_id)
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)
