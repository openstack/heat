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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation


class RBACPolicy(neutron.NeutronResource):
    """A Resource for managing RBAC policy in Neutron.

    This resource creates and manages Neutron RBAC policy,
    which allows to share Neutron networks and qos-policies
    to subsets of tenants.
    """

    support_status = support.SupportStatus(version='6.0.0')

    required_service_extension = 'rbac-policies'

    entity = 'rbac_policy'

    PROPERTIES = (
        OBJECT_TYPE, TARGET_TENANT, ACTION, OBJECT_ID, TENANT_ID
    ) = (
        'object_type', 'target_tenant', 'action', 'object_id', 'tenant_id'
    )

    OBJECT_TYPE_KEYS = (
        OBJECT_NETWORK, OBJECT_QOS_POLICY,
    ) = (
        'network', 'qos_policy',
    )

    ACTION_KEYS = (
        ACCESS_AS_SHARED, ACCESS_AS_EXTERNAL,
    ) = (
        'access_as_shared', 'access_as_external',
    )

    # Change it when neutron supports more function in the future.
    SUPPORTED_TYPES_ACTIONS = {
        OBJECT_NETWORK: [ACCESS_AS_SHARED, ACCESS_AS_EXTERNAL],
        OBJECT_QOS_POLICY: [ACCESS_AS_SHARED],
    }

    properties_schema = {
        OBJECT_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of the object that RBAC policy affects.'),
            required=True,
            constraints=[
                constraints.AllowedValues(OBJECT_TYPE_KEYS)
            ]
        ),
        TARGET_TENANT: properties.Schema(
            properties.Schema.STRING,
            _('ID of the tenant to which the RBAC policy will be enforced.'),
            required=True,
            update_allowed=True
        ),
        ACTION: properties.Schema(
            properties.Schema.STRING,
            _('Action for the RBAC policy. The allowed actions differ for '
              'different object types - only %(network)s objects can have an '
              '%(external)s action.') % {'network': OBJECT_NETWORK,
                                         'external': ACCESS_AS_EXTERNAL},
            required=True,
            constraints=[
                constraints.AllowedValues(ACTION_KEYS)
            ]
        ),
        OBJECT_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the RBAC object.'),
            required=True
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The owner tenant ID. Only required if the caller has an '
              'administrative role and wants to create a RBAC for another '
              'tenant.')
        )
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.OBJECT_ID],
                client_plugin=self.client_plugin(),
                finder='find_resourceid_by_name_or_id',
                entity=self._get_client_res_type(props[self.OBJECT_TYPE])
            )
        ]

    def _get_client_res_type(self, object_type):
        client_plugin = self.client_plugin()
        if object_type == self.OBJECT_NETWORK:
            return client_plugin.RES_TYPE_NETWORK
        elif object_type == self.OBJECT_QOS_POLICY:
            return client_plugin.RES_TYPE_QOS_POLICY
        else:
            return object_type

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        rbac = self.client().create_rbac_policy(
            {'rbac_policy': props})['rbac_policy']
        self.resource_id_set(rbac['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().update_rbac_policy(
                self.resource_id, {'rbac_policy': prop_diff})

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client().delete_rbac_policy(self.resource_id)

    def validate(self):
        """Validate the provided properties."""
        super(RBACPolicy, self).validate()

        action = self.properties[self.ACTION]
        obj_type = self.properties[self.OBJECT_TYPE]

        # Validate obj_type and action per SUPPORTED_TYPES_ACTIONS.
        if action not in self.SUPPORTED_TYPES_ACTIONS[obj_type]:
            valid_actions = ', '.join(self.SUPPORTED_TYPES_ACTIONS[obj_type])
            msg = (_('Invalid action "%(action)s" for object type '
                     '%(obj_type)s. Valid actions: %(valid_actions)s') %
                   {'action': action, 'obj_type': obj_type,
                    'valid_actions': valid_actions})
            properties_section = self.properties.error_prefix[0]
            path = [self.stack.t.RESOURCES, self.t.name,
                    self.stack.t.get_section_name(properties_section),
                    self.ACTION]
            raise exception.StackValidationFailed(error='Property error',
                                                  path=path,
                                                  message=msg)


def resource_mapping():
    return {
        'OS::Neutron::RBACPolicy': RBACPolicy,
    }
