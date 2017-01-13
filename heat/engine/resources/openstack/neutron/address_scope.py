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
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support


class AddressScope(neutron.NeutronResource):
    """A resource for Neutron address scope.

    This resource can be associated with multiple subnet pools
    in a one-to-many relationship. The subnet pools under an
    address scope must not overlap.
    """

    required_service_extension = 'address-scope'

    entity = 'address_scope'

    support_status = support.SupportStatus(version='6.0.0')

    PROPERTIES = (
        NAME, SHARED, TENANT_ID, IP_VERSION,
    ) = (
        'name', 'shared', 'tenant_id', 'ip_version',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name for the address scope.'),
            update_allowed=True
        ),
        SHARED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether the address scope should be shared to other '
              'tenants. Note that the default policy setting '
              'restricts usage of this attribute to administrative '
              'users only, and restricts changing of shared address scope '
              'to unshared with update.'),
            default=False,
            update_allowed=True
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The owner tenant ID of the address scope. Only '
              'administrative users can specify a tenant ID '
              'other than their own.'),
            constraints=[constraints.CustomConstraint('keystone.project')]
        ),
        IP_VERSION: properties.Schema(
            properties.Schema.INTEGER,
            _('Address family of the address scope, which is 4 or 6.'),
            default=4,
            constraints=[
                constraints.AllowedValues([4, 6]),
            ]
        ),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        address_scope = self.client().create_address_scope(
            {'address_scope': props})['address_scope']
        self.resource_id_set(address_scope['id'])

    def handle_delete(self):
        if self.resource_id is None:
            return

        with self.client_plugin().ignore_not_found:
            self.client().delete_address_scope(self.resource_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client().update_address_scope(
                self.resource_id,
                {'address_scope': prop_diff})


def resource_mapping():
    return {
        'OS::Neutron::AddressScope': AddressScope
    }
