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

from heat.common.i18n import _
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class CinderVolumeType(resource.Resource):
    """
    A resource for creating cinder volume types.

    Note that default cinder security policy usage of this resource
    is limited to being used by administrators only.

    Here is an example cinder volume_type and cinder volume resources::

        heat_template_version: 2013-05-23
        description:  Heat Cinder creation with volume_type example
        resources:
          my_volume_type:
            type: OS::Cinder::VolumeType
            properties:
              name: volumeBackend
              metadata: {volume_backend_name: lvmdriver}
          my_volume:
            type: OS::Cinder::Volume
            properties:
              size: 1
              volume_type: {get_resource: my_volume_type}
    """

    support_status = support.SupportStatus(version='2015.1')

    default_client_name = 'cinder'

    PROPERTIES = (
        NAME, METADATA, IS_PUBLIC, DESCRIPTION,
    ) = (
        'name', 'metadata', 'is_public', 'description',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the volume type.'),
            required=True,
            update_allowed=True,
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('The extra specs key and value pairs of the volume type.'),
            update_allowed=True
        ),
        IS_PUBLIC: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether the volume type is accessible to the public.'),
            default=True,
            support_status=support.SupportStatus(version='5.0.0'),
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the volume type.'),
            update_allowed=True,
            support_status=support.SupportStatus(version='5.0.0'),
        ),
    }

    def handle_create(self):
        args = {
            'name': self.properties[self.NAME],
            'is_public': self.properties[self.IS_PUBLIC],
            'description': self.properties[self.DESCRIPTION]
        }

        volume_type = self.cinder().volume_types.create(**args)
        self.resource_id_set(volume_type.id)
        vtype_metadata = self.properties[self.METADATA]
        if vtype_metadata:
            volume_type.set_keys(vtype_metadata)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Update the name, description and metadata for volume type."""

        update_args = {}
        # Update the name, description of cinder volume type
        if self.DESCRIPTION in prop_diff:
            update_args['description'] = prop_diff.get(self.DESCRIPTION)
        if self.NAME in prop_diff:
            update_args['name'] = prop_diff.get(self.NAME)
        if update_args:
            self.cinder().volume_types.update(self.resource_id, **update_args)
        # Update the key-value pairs of cinder volume type.
        if self.METADATA in prop_diff:
            volume_type = self.cinder().volume_types.get(self.resource_id)
            old_keys = volume_type.get_keys()
            volume_type.unset_keys(old_keys)
            new_keys = prop_diff.get(self.METADATA)
            if new_keys is not None:
                volume_type.set_keys(new_keys)

    def handle_delete(self):
        if self.resource_id is None:
            return

        try:
            self.cinder().volume_types.delete(self.resource_id)
        except Exception as e:
            self.client_plugin().ignore_not_found(e)


def resource_mapping():
    return {
        'OS::Cinder::VolumeType': CinderVolumeType
    }
