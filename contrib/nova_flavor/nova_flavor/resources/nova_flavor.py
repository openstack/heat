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


class NovaFlavor(resource.Resource):
    """
    A resource for creating OpenStack virtual hardware templates.

    Due to default nova security policy usage of this resource is limited to
    being used by administrators only. The rights may also be delegated to
    other users by redefining the access controls on the nova-api server.

    Note that the current implementation of the Nova Flavor resource does not
    allow specifying the name and flavorid properties for the resource.
    This is done to avoid potential naming collision upon flavor creation as
    all flavor have a global scope.
    """

    PROPERTIES = (
        RAM, VCPUS, DISK, SWAP, EPHEMERAL,
        RXTX_FACTOR, EXTRA_SPECS,
    ) = (
        'ram', 'vcpus', 'disk', 'swap', 'ephemeral',
        'rxtx_factor', 'extra_specs',
    )

    properties_schema = {
        RAM: properties.Schema(
            properties.Schema.INTEGER,
            _('Memory in MB for the flavor.'),
            required=True
        ),
        VCPUS: properties.Schema(
            properties.Schema.INTEGER,
            _('Number of VCPUs for the flavor.'),
            required=True
        ),
        DISK: properties.Schema(
            properties.Schema.INTEGER,
            _('Size of local disk in GB. Set the value to 0 to remove limit '
              'on disk size.'),
            required=True,
            default=0
        ),
        SWAP: properties.Schema(
            properties.Schema.INTEGER,
            _('Swap space in MB.'),
            default=0
        ),
        EPHEMERAL: properties.Schema(
            properties.Schema.INTEGER,
            _('Size of a secondary ephemeral data disk in GB.'),
            default=0
        ),
        RXTX_FACTOR: properties.Schema(
            properties.Schema.NUMBER,
            _('RX/TX factor.'),
            default=1.0
        ),
        EXTRA_SPECS: properties.Schema(
            properties.Schema.MAP,
            _('Key/Value pairs to extend the capabilities of the flavor.'),
            update_allowed=True,
        ),

    }

    def __init__(self, name, json_snippet, stack):
        super(NovaFlavor, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        args = dict(self.properties)
        args['flavorid'] = 'auto'
        args['name'] = self.physical_resource_name()
        args['is_public'] = False
        flavor_keys = args.pop(self.EXTRA_SPECS)

        flavor = self.nova().flavors.create(**args)
        self.resource_id_set(flavor.id)
        if flavor_keys:
            flavor.set_keys(flavor_keys)

        tenant = self.stack.context.tenant_id
        # grant access to the active project and the admin project
        self.nova().flavor_access.add_tenant_access(flavor, tenant)
        self.nova().flavor_access.add_tenant_access(flavor, 'admin')

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Update nova flavor."""
        if self.EXTRA_SPECS in prop_diff:
            flavor = self.nova().flavors.get(self.resource_id)
            old_keys = flavor.get_keys()
            flavor.unset_keys(old_keys)
            new_keys = prop_diff.get(self.EXTRA_SPECS)
            if new_keys is not None:
                flavor.set_keys(new_keys)

    def handle_delete(self):
        if self.resource_id is None:
            return

        try:
            self.nova().flavors.delete(self.resource_id)
        except Exception as e:
            self.client_plugin('nova').ignore_not_found(e)


def resource_mapping():
    return {
        'OS::Nova::Flavor': NovaFlavor
    }
