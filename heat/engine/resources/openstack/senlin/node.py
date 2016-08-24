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

    _ACTION_STATUS = (
        ACTION_SUCCEEDED, ACTION_FAILED,
    ) = (
        'SUCCEEDED', 'FAILED',
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
        updaters = dict()
        UPDATE_PROPS = [self.NAME, self.METADATA, self.PROFILE]
        if any(p in prop_diff for p in UPDATE_PROPS):
            params = dict((k, v) for k, v in prop_diff.items()
                          if k in UPDATE_PROPS)
            if self.PROFILE in params:
                params['profile_id'] = params.pop(self.PROFILE)
            updaters['profile_update'] = {
                'params': params,
                'finished': False,
            }

        return updaters

    def check_update_complete(self, updaters):
        def check_action(updater, set_key):
            action = self.client().get_action(updater['action'])
            if action.status == self.ACTION_SUCCEEDED:
                updater[set_key] = True
            elif action.status == self.ACTION_FAILED:
                raise exception.ResourceInError(
                    status_reason=action.status_reason,
                    resource_status=action.status,
                )

        if not updaters:
            return True
        profile_update = updaters.get('profile_update')
        if profile_update and not profile_update['finished']:
            if 'action' not in profile_update:
                resp = self.client().update_node(
                    self.resource_id, **profile_update['params'])
                profile_update['action'] = resp.location.split('/')[-1]
                return False
            else:
                check_action(profile_update, 'finished')
                if not profile_update['finished']:
                    return False

        return True

    def _resolve_attribute(self, name):
        node = self.client().get_node(self.resource_id,
                                      args={'show_details': True})
        return getattr(node, name, None)


def resource_mapping():
    return {
        'OS::Senlin::Node': Node
    }
