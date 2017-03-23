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


class ManilaShareType(resource.Resource):
    """A resource for creating manila share type.

    A share_type is an administrator-defined "type of service", comprised of
    a tenant visible description, and a list of non-tenant-visible key/value
    pairs (extra_specs) which the Manila scheduler uses to make scheduling
    decisions for shared filesystem tasks.

    Please note that share type is intended to use mostly by administrators.
    So it is very likely that Manila will prohibit creation of the resource
    without administration grants.
    """

    support_status = support.SupportStatus(version='5.0.0')

    PROPERTIES = (
        NAME, IS_PUBLIC, DRIVER_HANDLES_SHARE_SERVERS, EXTRA_SPECS,
        SNAPSHOT_SUPPORT
    ) = (
        'name', 'is_public', 'driver_handles_share_servers', 'extra_specs',
        'snapshot_support'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the share type.'),
            required=True
        ),
        IS_PUBLIC: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Defines if share type is accessible to the public.'),
            default=True
        ),
        DRIVER_HANDLES_SHARE_SERVERS: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Required extra specification. '
              'Defines if share drivers handles share servers.'),
            required=True,
        ),
        EXTRA_SPECS: properties.Schema(
            properties.Schema.MAP,
            _("Extra specs key-value pairs defined for share type."),
            update_allowed=True
        ),
        SNAPSHOT_SUPPORT: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Boolean extra spec that used for filtering of backends by '
              'their capability to create share snapshots.'),
            support_status=support.SupportStatus(version='6.0.0'),
            default=True
        )
    }

    default_client_name = 'manila'

    entity = 'share_types'

    def handle_create(self):
        share_type = self.client().share_types.create(
            name=self.properties.get(self.NAME),
            spec_driver_handles_share_servers=self.properties.get(
                self.DRIVER_HANDLES_SHARE_SERVERS),
            is_public=self.properties.get(self.IS_PUBLIC),
            spec_snapshot_support=self.properties.get(self.SNAPSHOT_SUPPORT)
        )
        self.resource_id_set(share_type.id)
        extra_specs = self.properties.get(self.EXTRA_SPECS)
        if extra_specs:
            share_type.set_keys(extra_specs)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if self.EXTRA_SPECS in prop_diff:
            share_type = self.client().share_types.get(self.resource_id)
            extra_specs_old = self.properties.get(self.EXTRA_SPECS)
            if extra_specs_old:
                share_type.unset_keys(extra_specs_old)
            share_type.set_keys(prop_diff.get(self.EXTRA_SPECS))

    def parse_live_resource_data(self, resource_properties, resource_data):
        extra_specs = resource_data.pop(self.EXTRA_SPECS)
        extra_specs.pop(self.SNAPSHOT_SUPPORT)
        extra_specs.pop(self.DRIVER_HANDLES_SHARE_SERVERS)
        return {self.EXTRA_SPECS: extra_specs}


def resource_mapping():
    return {
        'OS::Manila::ShareType': ManilaShareType
    }
