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

from six.moves.urllib import parse

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import translation


class KeystoneRegion(resource.Resource):
    """Heat Template Resource for Keystone Region.

    This plug-in helps to create, update and delete a keystone region. Also
    it can be used for enable or disable a given keystone region.
    """

    support_status = support.SupportStatus(
        version='6.0.0',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    entity = 'regions'

    PROPERTIES = (
        ID, PARENT_REGION, DESCRIPTION, ENABLED
    ) = (
        'id', 'parent_region', 'description', 'enabled'
    )

    properties_schema = {
        ID: properties.Schema(
            properties.Schema.STRING,
            _('The user-defined region ID and should unique to the OpenStack '
              'deployment. While creating the region, heat will url encode '
              'this ID.')
        ),
        PARENT_REGION: properties.Schema(
            properties.Schema.STRING,
            _('If the region is hierarchically a child of another region, '
              'set this parameter to the ID of the parent region.'),
            update_allowed=True,
            constraints=[constraints.CustomConstraint('keystone.region')]
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of keystone region.'),
            update_allowed=True
        ),
        ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('This region is enabled or disabled.'),
            default=True,
            update_allowed=True
        )
    }

    def translation_rules(self, properties):
        return [
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.PARENT_REGION],
                client_plugin=self.client_plugin(),
                finder='get_region_id'
            )
        ]

    def client(self):
        return super(KeystoneRegion, self).client().client

    def handle_create(self):
        region_id = self.properties[self.ID]
        description = self.properties[self.DESCRIPTION]
        parent_region = self.properties[self.PARENT_REGION]
        enabled = self.properties[self.ENABLED]

        region = self.client().regions.create(
            id=parse.quote(region_id) if region_id else None,
            parent_region=parent_region,
            description=description,
            enabled=enabled)

        self.resource_id_set(region.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            description = prop_diff.get(self.DESCRIPTION)
            enabled = prop_diff.get(self.ENABLED)
            parent_region = prop_diff.get(self.PARENT_REGION)

            self.client().regions.update(
                region=self.resource_id,
                parent_region=parent_region,
                description=description,
                enabled=enabled
            )

    def parse_live_resource_data(self, resource_properties, resource_data):
        return {
            self.DESCRIPTION: resource_data.get(self.DESCRIPTION),
            self.ENABLED: resource_data.get(self.ENABLED),
            self.PARENT_REGION: resource_data.get('parent_region_id')
        }


def resource_mapping():
    return {
        'OS::Keystone::Region': KeystoneRegion
    }
