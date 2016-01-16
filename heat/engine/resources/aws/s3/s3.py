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
import six
from six.moves.urllib import parse as urlparse

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource


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

    ATTRIBUTES = (
        DOMAIN_NAME, WEBSITE_URL,
    ) = (
        'DomainName', 'WebsiteURL',
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
        DOMAIN_NAME: attributes.Schema(
            _('The DNS name of the specified bucket.'),
            type=attributes.Schema.STRING
        ),
        WEBSITE_URL: attributes.Schema(
            _('The website endpoint for the specified bucket.'),
            type=attributes.Schema.STRING
        ),
    }

    default_client_name = 'swift'

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
        tenant_username = '%s:%s' % (con.project_name, con.username)
        if ac in ('PublicRead', 'PublicReadWrite'):
            headers['X-Container-Read'] = '.r:*'
        elif ac == 'AuthenticatedRead':
            headers['X-Container-Read'] = con.project_name
        else:
            headers['X-Container-Read'] = tenant_username

        if ac == 'PublicReadWrite':
            headers['X-Container-Write'] = '.r:*'
        else:
            headers['X-Container-Write'] = tenant_username

        self.client().put_container(container, headers)
        self.resource_id_set(container)

    def handle_delete(self):
        """Perform specified delete policy."""
        if self.resource_id is None:
            return
        try:
            self.client().delete_container(self.resource_id)
        except Exception as ex:
            if self.client_plugin().is_conflict(ex):
                container, objects = self.client().get_container(
                    self.resource_id)
                if objects:
                    msg = _("The bucket you tried to delete is not empty (%s)."
                            ) % self.resource_id
                    raise exception.ResourceActionNotSupported(action=msg)
            self.client_plugin().ignore_not_found(ex)

    def get_reference_id(self):
        return six.text_type(self.resource_id)

    def _resolve_attribute(self, name):
        url = self.client().get_auth()[0]
        parsed = list(urlparse.urlparse(url))
        if name == self.DOMAIN_NAME:
            return parsed[1].split(':')[0]
        elif name == self.WEBSITE_URL:
            return '%s://%s%s/%s' % (parsed[0], parsed[1], parsed[2],
                                     self.resource_id)


def resource_mapping():
    return {
        'AWS::S3::Bucket': S3Bucket,
    }
