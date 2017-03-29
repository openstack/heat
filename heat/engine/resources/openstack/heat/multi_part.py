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

import email
from email.mime import multipart
from email.mime import text
import os
from oslo_utils import uuidutils

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.heat import software_config
from heat.engine import support
from heat.rpc import api as rpc_api


class MultipartMime(software_config.SoftwareConfig):
    """Assembles a collection of software configurations as a multi-part mime.

    Parts in the message can be populated with inline configuration or
    references to other config resources. If the referenced resource is itself
    a valid multi-part mime message, that will be broken into parts and
    those parts appended to this message.

    The resulting multi-part mime message will be stored by the configs API
    and can be referenced in properties such as OS::Nova::Server user_data.

    This resource is generally used to build a list of cloud-init
    configuration elements including scripts and cloud-config. Since
    cloud-init is boot-only configuration, any changes to the definition
    will result in the replacement of all servers which reference it.
    """

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        PARTS, CONFIG, FILENAME, TYPE, SUBTYPE
    ) = (
        'parts', 'config', 'filename', 'type', 'subtype'
    )

    TYPES = (
        TEXT, MULTIPART
    ) = (
        'text', 'multipart'
    )

    properties_schema = {
        PARTS: properties.Schema(
            properties.Schema.LIST,
            _('Parts belonging to this message.'),
            default=[],
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    CONFIG: properties.Schema(
                        properties.Schema.STRING,
                        _('Content of part to attach, either inline or by '
                          'referencing the ID of another software config '
                          'resource.'),
                        required=True
                    ),
                    FILENAME: properties.Schema(
                        properties.Schema.STRING,
                        _('Optional filename to associate with part.')
                    ),
                    TYPE: properties.Schema(
                        properties.Schema.STRING,
                        _('Whether the part content is text or multipart.'),
                        default=TEXT,
                        constraints=[constraints.AllowedValues(TYPES)]
                    ),
                    SUBTYPE: properties.Schema(
                        properties.Schema.STRING,
                        _('Optional subtype to specify with the type.')
                    ),
                }
            )
        )
    }

    message = None

    def handle_create(self):
        props = {
            rpc_api.SOFTWARE_CONFIG_NAME: self.physical_resource_name(),
            rpc_api.SOFTWARE_CONFIG_CONFIG: self.get_message(),
            rpc_api.SOFTWARE_CONFIG_GROUP: 'Heat::Ungrouped'
        }
        sc = self.rpc_client().create_software_config(self.context, **props)
        self.resource_id_set(sc[rpc_api.SOFTWARE_CONFIG_ID])

    def get_message(self):
        if self.message:
            return self.message

        subparts = []
        for item in self.properties[self.PARTS]:
            config = item.get(self.CONFIG)
            part_type = item.get(self.TYPE, self.TEXT)
            part = config

            if uuidutils.is_uuid_like(config):
                with self.rpc_client().ignore_error_by_name('NotFound'):
                    sc = self.rpc_client().show_software_config(
                        self.context, config)
                    part = sc[rpc_api.SOFTWARE_CONFIG_CONFIG]

            if part_type == self.MULTIPART:
                self._append_multiparts(subparts, part)
            else:
                filename = item.get(self.FILENAME, '')
                subtype = item.get(self.SUBTYPE, '')
                self._append_part(subparts, part, subtype, filename)

        mime_blob = multipart.MIMEMultipart(_subparts=subparts)
        self.message = mime_blob.as_string()
        return self.message

    @staticmethod
    def _append_multiparts(subparts, multi_part):
        multi_parts = email.message_from_string(multi_part)
        if not multi_parts or not multi_parts.is_multipart():
            return

        for part in multi_parts.get_payload():
            MultipartMime._append_part(
                subparts,
                part.get_payload(),
                part.get_content_subtype(),
                part.get_filename())

    @staticmethod
    def _append_part(subparts, part, subtype, filename):
        if not subtype and filename:
            subtype = os.path.splitext(filename)[0]

        msg = MultipartMime._create_message(part, subtype, filename)
        subparts.append(msg)

    @staticmethod
    def _create_message(part, subtype, filename):
        charset = 'us-ascii'
        try:
            part.encode(charset)
        except UnicodeEncodeError:
            charset = 'utf-8'
        msg = (text.MIMEText(part, _subtype=subtype,
                             _charset=charset)
               if subtype else text.MIMEText(part, _charset=charset))

        if filename:
            msg.add_header('Content-Disposition', 'attachment',
                           filename=filename)
        return msg


def resource_mapping():
    return {
        'OS::Heat::MultipartMime': MultipartMime,
    }
