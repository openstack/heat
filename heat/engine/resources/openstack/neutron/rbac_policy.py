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
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support

from neutronclient.neutron import v2_0 as neutronV20


class RBACPolicy(neutron.NeutronResource):
    """A Resource for managing RBAC policy in Neutron.

    This resource creates and manages Neutron RBAC policy,
    which allows to share Neutron networks to subsets of tenants.
    """

    support_status = support.SupportStatus(version='6.0.0')

    required_service_extension = 'rbac-policies'

    PROPERTIES = (
        OBJECT_TYPE, TARGET_TENANT, ACTION, OBJECT_ID, TENANT_ID
    ) = (
        'object_type', 'target_tenant', 'action', 'object_id', 'tenant_id'
    )

    # Change it when neutron supports more function in the future.
    SUPPORTED_TYPES_ACTIONS = {'network': ['access_as_shared']}

    properties_schema = {
        OBJECT_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of the object that RBAC policy affects.'),
            required=True,
        ),
        TARGET_TENANT: properties.Schema(
            properties.Schema.STRING,
            _('ID of the tenant to which the RBAC policy will be enforced.'),
            required=True,
            update_allowed=True
        ),
        ACTION: properties.Schema(
            properties.Schema.STRING,
            _('Action for the RBAC policy.'),
            required=True,
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

    def prepare_properties(self, properties, name):
        props = super(RBACPolicy, self).prepare_properties(properties, name)

        obj_type = props.get(self.OBJECT_TYPE)
        obj_id_or_name = props.get(self.OBJECT_ID)
        obj_id = neutronV20.find_resourceid_by_name_or_id(self.client(),
                                                          obj_type,
                                                          obj_id_or_name)
        props['object_id'] = obj_id
        return props

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

    def _show_resource(self):
        return self.client().show_rbac_policy(self.resource_id)['rbac_policy']

    def validate(self):
        """Validate the provided params."""
        super(RBACPolicy, self).validate()

        action = self.properties[self.ACTION]
        obj_type = self.properties[self.OBJECT_TYPE]
        obj_id_or_name = self.properties[self.OBJECT_ID]

        # Validate obj_type and action per SUPPORTED_TYPES_ACTIONS.
        if obj_type not in self.SUPPORTED_TYPES_ACTIONS:
            msg = (_("Invalid object_type: %(obj_type)s. "
                     "Valid object_type :%(value)s") %
                   {'obj_type': obj_type,
                    'value': self.SUPPORTED_TYPES_ACTIONS.keys()})
            raise exception.StackValidationFailed(message=msg)
        if action not in self.SUPPORTED_TYPES_ACTIONS[obj_type]:
            msg = (_("Invalid action %(action)s for object type "
                   "%(obj_type)s. Valid actions :%(value)s") %
                   {'action': action, 'obj_type': obj_type,
                    'value': self.SUPPORTED_TYPES_ACTIONS[obj_type]})
            raise exception.StackValidationFailed(message=msg)

        # Make sure the value of object_id is correct.
        neutronV20.find_resourceid_by_name_or_id(self.client(),
                                                 obj_type,
                                                 obj_id_or_name)


def resource_mapping():
    return {
        'OS::Neutron::RBACPolicy': RBACPolicy,
    }
