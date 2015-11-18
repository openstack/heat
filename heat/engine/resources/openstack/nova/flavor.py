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
from heat.engine import attributes
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class NovaFlavor(resource.Resource):
    """A resource for creating OpenStack virtual hardware templates.

    Due to default nova security policy usage of this resource is limited to
    being used by administrators only. The rights may also be delegated to
    other users by redefining the access controls on the nova-api server.

    Note that the current implementation of the Nova Flavor resource does not
    allow specifying the name and flavorid properties for the resource.
    This is done to avoid potential naming collision upon flavor creation as
    all flavor have a global scope.

    Here is an example nova flavor resource::

        heat_template_version: 2013-05-23
        description:  Heat Flavor creation example
        resources:
          test_flavor:
            type: OS::Nova::Flavor
            properties:
              ram: 1024
              vcpus: 1
              disk: 20
              swap: 2
              extra_specs: {"quota:disk_read_bytes_sec": "10240000"}
    """

    support_status = support.SupportStatus(version='2014.2')

    default_client_name = 'nova'

    required_service_extension = 'os-flavor-manage'

    entity = 'flavors'

    PROPERTIES = (
        RAM, VCPUS, DISK, SWAP, EPHEMERAL,
        RXTX_FACTOR, EXTRA_SPECS, IS_PUBLIC
    ) = (
        'ram', 'vcpus', 'disk', 'swap', 'ephemeral',
        'rxtx_factor', 'extra_specs', 'is_public',
    )

    ATTRIBUTES = (
        IS_PUBLIC_ATTR,
    ) = (
        'is_public',
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
            _('Size of local disk in GB. The "0" size is a special case that '
              'uses the native base image size as the size of the ephemeral '
              'root volume.'),
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
        IS_PUBLIC: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Scope of flavor accessibility. Public or private.'
              'Default value is True, means public, shared '
              'across all projects.'),
            default=True,
            support_status=support.SupportStatus(version='6.0.0'),
        ),

    }

    attributes_schema = {
        IS_PUBLIC_ATTR: attributes.Schema(
            _('Whether the flavor is shared across all projects.'),
            support_status=support.SupportStatus(version='6.0.0'),
            type=attributes.Schema.BOOLEAN
        ),
    }

    def handle_create(self):
        args = dict(self.properties)
        args['flavorid'] = 'auto'
        args['name'] = self.physical_resource_name()
        flavor_keys = args.pop(self.EXTRA_SPECS)

        flavor = self.client().flavors.create(**args)
        self.resource_id_set(flavor.id)
        if flavor_keys:
            flavor.set_keys(flavor_keys)

        tenant = self.stack.context.tenant_id
        if not args['is_public']:
            # grant access only to the active project(private flavor)
            self.client().flavor_access.add_tenant_access(flavor, tenant)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Update nova flavor."""
        if self.EXTRA_SPECS in prop_diff:
            flavor = self.client().flavors.get(self.resource_id)
            old_keys = flavor.get_keys()
            flavor.unset_keys(old_keys)
            new_keys = prop_diff.get(self.EXTRA_SPECS)
            if new_keys is not None:
                flavor.set_keys(new_keys)

    def _resolve_attribute(self, name):
        flavor = self.client().flavors.get(self.resource_id)
        if name == self.IS_PUBLIC_ATTR:
            return getattr(flavor, name)


def resource_mapping():
    return {
        'OS::Nova::Flavor': NovaFlavor
    }
