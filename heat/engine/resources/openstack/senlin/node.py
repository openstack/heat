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

import copy

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.senlin import res_base
from heat.engine import support
from heat.engine import translation


class Node(res_base.BaseSenlinResource):
    """A resource that creates a Senlin Node.

    Node is an object that belongs to at most one Cluster, it can be created
    based on a profile.
    """

    entity = 'node'

    PROPERTIES = (
        NAME, METADATA, PROFILE, CLUSTER
    ) = (
        'name', 'metadata', 'profile', 'cluster'
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
        CLUSTER: properties.Schema(
            properties.Schema.STRING,
            _('The name of senlin cluster to attach to.'),
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('senlin.cluster')
            ],
            support_status=support.SupportStatus(version='8.0.0'),
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

    def translation_rules(self, props):
        rules = [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.PROFILE],
                client_plugin=self.client_plugin(),
                finder='get_profile_id'),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.CLUSTER],
                client_plugin=self.client_plugin(),
                finder='get_cluster_id'),
        ]
        return rules

    def handle_create(self):
        params = {
            'name': (self.properties[self.NAME] or
                     self.physical_resource_name()),
            'metadata': self.properties[self.METADATA],
            'profile_id': self.properties[self.PROFILE],
            'cluster_id': self.properties[self.CLUSTER],
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

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        actions = []
        if prop_diff:
            old_cluster = None
            new_cluster = None
            if self.PROFILE in prop_diff:
                prop_diff['profile_id'] = prop_diff.pop(self.PROFILE)
            if self.CLUSTER in prop_diff:
                old_cluster = self.properties[self.CLUSTER]
                new_cluster = prop_diff.pop(self.CLUSTER)
            if old_cluster:
                params = {
                    'cluster': old_cluster,
                    'nodes': [self.resource_id],
                }
                action = {
                    'func': 'cluster_del_nodes',
                    'action_id': None,
                    'params': params,
                    'done': False,
                }
                actions.append(action)
            if prop_diff:
                node = self.client().get_node(self.resource_id)
                params = copy.deepcopy(prop_diff)
                params['node'] = node
                action = {
                    'func': 'update_node',
                    'action_id': None,
                    'params': params,
                    'done': False,
                }
                actions.append(action)
            if new_cluster:
                params = {
                    'cluster': new_cluster,
                    'nodes': [self.resource_id],
                }
                action = {
                    'func': 'cluster_add_nodes',
                    'action_id': None,
                    'params': params,
                    'done': False,
                }
                actions.append(action)

        return actions

    def check_update_complete(self, actions):
        return self.client_plugin().execute_actions(actions)

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        node = self.client().get_node(self.resource_id, details=True)
        return getattr(node, name, None)

    def parse_live_resource_data(self, resource_properties, resource_data):
        reality = {}

        for key in self._update_allowed_properties:
            if key == self.PROFILE:
                value = resource_data.get('profile_id')
            elif key == self.CLUSTER:
                value = resource_data.get('cluster_id')
            else:
                value = resource_data.get(key)
            reality.update({key: value})

        return reality


def resource_mapping():
    return {
        'OS::Senlin::Node': Node
    }
