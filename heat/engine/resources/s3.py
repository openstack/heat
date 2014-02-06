
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

from heat.engine import clients
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common import log as logging
from heat.openstack.common.py3kcompat import urlutils

logger = logging.getLogger(__name__)


class S3Bucket(resource.Resource):

    PROPERTIES = (
        ACCESS_CONTROL, WEBSITE_CONFIGURATION, TAGS,
    ) = (
        'AccessControl', 'WebsiteConfiguration', 'Tags',
    )

    _WEBSITE_CONFIGURATION_KEYS = (
        WEBSITE_CONFIGURATION_INDEX_DOCUMENT,
        WEBSITE_CONFIGURATION_ERROR_DOCUMENT,
    ) = (
        'IndexDocument',
        'ErrorDocument',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        ACCESS_CONTROL: properties.Schema(
            properties.Schema.STRING,
            _('A predefined access control list (ACL) that grants '
              'permissions on the bucket.'),
            constraints=[
                constraints.AllowedValues(['Private', 'PublicRead',
                                           'PublicReadWrite',
                                           'AuthenticatedRead',
                                           'BucketOwnerRead',
                                           'BucketOwnerFullControl']),
            ]
        ),
        WEBSITE_CONFIGURATION: properties.Schema(
            properties.Schema.MAP,
            _('Information used to configure the bucket as a static website.'),
            schema={
                WEBSITE_CONFIGURATION_INDEX_DOCUMENT: properties.Schema(
                    properties.Schema.STRING,
                    _('The name of the index document.')
                ),
                WEBSITE_CONFIGURATION_ERROR_DOCUMENT: properties.Schema(
                    properties.Schema.STRING,
                    _('The name of the error document.')
                ),
            }
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('Tags to attach to the bucket.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    TAG_KEY: properties.Schema(
                        properties.Schema.STRING,
                        _('The tag key name.'),
                        required=True
                    ),
                    TAG_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        _('The tag value.'),
                        required=True
                    ),
                },
            )
        ),
    }

    attributes_schema = {
        'DomainName': _('The DNS name of the specified bucket.'),
        'WebsiteURL': _('The website endpoint for the specified bucket.')
    }

    def tags_to_headers(self):
        if self.properties[self.TAGS] is None:
            return {}
        return dict(
            ('X-Container-Meta-S3-Tag-' + tm[self.TAG_KEY], tm[self.TAG_VALUE])
            for tm in self.properties[self.TAGS])

    def handle_create(self):
        """Create a bucket."""
        container = self.physical_resource_name()
        headers = self.tags_to_headers()
        logger.debug(_('S3Bucket create container %(container)s with headers '
                     '%(headers)s') % {
                         'container': container, 'headers': headers})
        if self.properties[self.WEBSITE_CONFIGURATION] is not None:
            sc = self.properties[self.WEBSITE_CONFIGURATION]
            index_doc = sc[self.WEBSITE_CONFIGURATION_INDEX_DOCUMENT]
            error_doc = sc[self.WEBSITE_CONFIGURATION_ERROR_DOCUMENT]
            # we will assume that swift is configured for the staticweb
            # wsgi middleware
            headers['X-Container-Meta-Web-Index'] = index_doc
            headers['X-Container-Meta-Web-Error'] = error_doc

        con = self.context
        ac = self.properties[self.ACCESS_CONTROL]
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

    def handle_delete(self):
        """Perform specified delete policy."""
        logger.debug(_('S3Bucket delete container %s') % self.resource_id)
        if self.resource_id is not None:
            try:
                self.swift().delete_container(self.resource_id)
            except clients.swiftclient.ClientException as ex:
                logger.warn(_("Delete container failed: %s") % str(ex))

    def FnGetRefId(self):
        return unicode(self.resource_id)

    def _resolve_attribute(self, name):
        url = self.swift().get_auth()[0]
        parsed = list(urlutils.urlparse(url))
        if name == 'DomainName':
            return parsed[1].split(':')[0]
        elif name == 'WebsiteURL':
            return '%s://%s%s/%s' % (parsed[0], parsed[1], parsed[2],
                                     self.resource_id)


def resource_mapping():
    if clients.swiftclient is None:
        return {}

    return {
        'AWS::S3::Bucket': S3Bucket,
    }
