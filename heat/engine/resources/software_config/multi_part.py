
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
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os

from heat.common import exception
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.software_config import software_config
from heat.openstack.common.gettextutils import _


class MultipartMime(software_config.SoftwareConfig):
    '''
    A resource which assembles a collection of software configurations
    as a multi-part mime message.

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
    '''

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
            _('Parts belonging to this messsage.'),
            default=[],
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    CONFIG: properties.Schema(
                        properties.Schema.STRING,
                        _('Content of part to attach, either inline or by '
                          'referencing the ID of another software config '
                          'resource'),
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
        props = {self.NAME: self.physical_resource_name()}
        props[self.CONFIG] = self.get_message()
        sc = self.heat().software_configs.create(**props)
        self.resource_id_set(sc.id)

    def get_message(self):
        if self.message:
            return self.message

        subparts = []
        for item in self.properties.get(self.PARTS):
            config = item.get(self.CONFIG)
            part_type = item.get(self.TYPE, self.TEXT)
            part = config
            try:
                part = self.get_software_config(self.heat(), config)
            except exception.SoftwareConfigMissing:
                pass

            if part_type == self.MULTIPART:
                self._append_multiparts(subparts, part)
            else:
                filename = item.get(self.FILENAME, '')
                subtype = item.get(self.SUBTYPE, '')
                self._append_part(subparts, part, subtype, filename)

        mime_blob = MIMEMultipart(_subparts=subparts)
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
        msg = MIMEText(part, _subtype=subtype) if subtype else MIMEText(part)
        if filename:
            msg.add_header('Content-Disposition', 'attachment',
                           filename=filename)
        return msg


def resource_mapping():
    return {
        'OS::Heat::MultipartMime': MultipartMime,
    }
