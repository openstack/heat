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

    PROPERTIES = (
        NAME, METADATA,
    ) = (
        'name', 'metadata',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the volume type.'),
            required=True
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('The extra specs key and value pairs of the volume type.'),
            update_allowed=True
        ),
    }

    def handle_create(self):
        vtype_name = self.properties.get(self.NAME)
        volume_type = self.cinder().volume_types.create(vtype_name)
        self.resource_id_set(volume_type.id)
        vtype_metadata = self.properties.get(self.METADATA)
        if vtype_metadata:
            volume_type.set_keys(vtype_metadata)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Update the key-value pairs of cinder volume type."""
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
            self.client_plugin('cinder').ignore_not_found(e)


def resource_mapping():
    return {
        'OS::Cinder::VolumeType': CinderVolumeType
    }
