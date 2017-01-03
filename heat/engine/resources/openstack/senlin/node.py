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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class Node(resource.Resource):
    """A resource that creates a Senlin Node.

    Node is an object that belongs to at most one Cluster, it can be created
    based on a profile.
    """

    support_status = support.SupportStatus(version='6.0.0')

    default_client_name = 'senlin'

    PROPERTIES = (
        NAME, METADATA, PROFILE,
    ) = (
        'name', 'metadata', 'profile',
    )

    _NODE_STATUS = (
        INIT, ACTIVE, CREATING,
    ) = (
        'INIT', 'ACTIVE', 'CREATING',
    )

    ATTRIBUTES = (
        ATTR_DETAILS, ATTR_CLUSTER,
    ) = (
        'details', 'cluster_id'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the senlin node. By default, physical resource name '
              'is used.'),
            update_allowed=True,
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Metadata key-values defined for node.'),
            update_allowed=True,
        ),
        PROFILE: properties.Schema(
            properties.Schema.STRING,
            _('Name or ID of senlin profile to create this node.'),
            required=True,
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('senlin.profile')
            ]
        ),
    }

    attributes_schema = {
        ATTR_DETAILS: attributes.Schema(
            _("The details of physical object."),
            type=attributes.Schema.MAP
        ),
        ATTR_CLUSTER: attributes.Schema(
            _("The cluster ID this node belongs to."),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        params = {
            'name': (self.properties[self.NAME] or
                     self.physical_resource_name()),
            'metadata': self.properties[self.METADATA],
            'profile_id': self.properties[self.PROFILE],
        }

        node = self.client().create_node(**params)
        action_id = node.location.split('/')[-1]
        self.resource_id_set(node.id)
        return action_id

    def check_create_complete(self, action_id):
        return self.client_plugin().check_action_status(action_id)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client().delete_node(self.resource_id)
        return self.resource_id

    def check_delete_complete(self, res_id):
        if not res_id:
            return True

        try:
            self.client().get_node(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            return True
        return False

    def _show_resource(self):
        node = self.client().get_node(self.resource_id)
        return node.to_dict()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        action_id = None
        if prop_diff:
            if self.PROFILE in prop_diff:
                prop_diff['profile_id'] = prop_diff.pop(self.PROFILE)
            node_obj = self.client().get_node(self.resource_id)
            node = self.client().update_node(
                node_obj, **prop_diff)
            action_id = node.location.split('/')[-1]

        return action_id

    def check_update_complete(self, action_id):
        if action_id is None:
            return True
        return self.client_plugin().check_action_status(action_id)

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        node = self.client().get_node(self.resource_id, details=True)
        return getattr(node, name, None)


def resource_mapping():
    return {
        'OS::Senlin::Node': Node
    }
