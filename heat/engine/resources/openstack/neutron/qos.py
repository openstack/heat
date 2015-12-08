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
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support


class QoSPolicy(neutron.NeutronResource):
    """A resource for Neutron QoS Policy.

    This QoS policy can be associated with neutron resources,
    such as port and network, to provide QoS capabilities.

    The default policy usage of this resource is limited to
    administrators only.
    """

    required_service_extension = 'qos'

    support_status = support.SupportStatus(version='6.0.0')

    PROPERTIES = (
        NAME, DESCRIPTION, SHARED, TENANT_ID,
    ) = (
        'name', 'description', 'shared', 'tenant_id',
    )

    ATTRIBUTES = (
        RULES_ATTR,
    ) = (
        'rules',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name for the QoS policy.'),
            required=True,
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('The description for the QoS policy.'),
            update_allowed=True
        ),
        SHARED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether this QoS policy should be shared to other tenants.'),
            default=False,
            update_allowed=True
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The owner tenant ID of this QoS policy.')
        ),
    }

    attributes_schema = {
        RULES_ATTR: attributes.Schema(
            _("A list of all rules for the QoS policy."),
            type=attributes.Schema.LIST
        )
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        policy = self.client().create_qos_policy({'policy': props})['policy']
        self.resource_id_set(policy['id'])

    def handle_delete(self):
        if self.resource_id is None:
            return

        with self.client_plugin().ignore_not_found:
            self.client().delete_qos_policy(self.resource_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            props = self.prepare_update_properties(json_snippet)
            self.client().update_qos_policy(
                self.resource_id,
                {'policy': props})

    def _show_resource(self):
        return self.client().show_qos_policy(
            self.resource_id)['policy']


def resource_mapping():
    return {
        'OS::Neutron::QoSPolicy': QoSPolicy,
    }
