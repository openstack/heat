#    Copyright 2015 IBM Corp.
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

import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.senlin import res_base
from heat.engine import support
from heat.engine import translation


class Cluster(res_base.BaseSenlinResource):
    """A resource that creates a Senlin Cluster.

    Cluster resource in senlin can create and manage objects of
    the same nature, e.g. Nova servers, Heat stacks, Cinder volumes, etc.
    The collection of these objects is referred to as a cluster.
    """

    entity = 'cluster'

    PROPERTIES = (
        NAME, PROFILE, DESIRED_CAPACITY, MIN_SIZE, MAX_SIZE,
        METADATA, TIMEOUT, POLICIES,
    ) = (
        'name', 'profile', 'desired_capacity', 'min_size', 'max_size',
        'metadata', 'timeout', 'policies',
    )

    ATTRIBUTES = (
        ATTR_NAME, ATTR_METADATA, ATTR_NODES, ATTR_DESIRED_CAPACITY,
        ATTR_MIN_SIZE, ATTR_MAX_SIZE, ATTR_POLICIES, ATTR_COLLECT,
    ) = (
        "name", 'metadata', 'nodes', 'desired_capacity',
        'min_size', 'max_size', 'policies', 'collect',
    )

    _POLICIES = (
        P_POLICY, P_ENABLED,
    ) = (
        "policy", "enabled",
    )

    _CLUSTER_STATUS = (
        CLUSTER_INIT, CLUSTER_ACTIVE, CLUSTER_ERROR, CLUSTER_WARNING,
        CLUSTER_CREATING, CLUSTER_DELETING, CLUSTER_UPDATING
    ) = (
        'INIT', 'ACTIVE', 'ERROR', 'WARNING',
        'CREATING', 'DELETING', 'UPDATING'
    )

    properties_schema = {
        PROFILE: properties.Schema(
            properties.Schema.STRING,
            _('The name or id of the Senlin profile.'),
            required=True,
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('senlin.profile')
            ]
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the cluster. By default, physical resource name '
              'is used.'),
            update_allowed=True,
        ),
        DESIRED_CAPACITY: properties.Schema(
            properties.Schema.INTEGER,
            _('Desired initial number of resources in cluster.'),
            default=0,
            update_allowed=True,
        ),
        MIN_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('Minimum number of resources in the cluster.'),
            default=0,
            update_allowed=True,
            constraints=[
                constraints.Range(min=0)
            ]
        ),
        MAX_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('Maximum number of resources in the cluster. '
              '-1 means unlimited.'),
            default=-1,
            update_allowed=True,
            constraints=[
                constraints.Range(min=-1)
            ]
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Metadata key-values defined for cluster.'),
            update_allowed=True,
            default={},
        ),
        TIMEOUT: properties.Schema(
            properties.Schema.INTEGER,
            _('The number of seconds to wait for the cluster actions.'),
            update_allowed=True,
            constraints=[
                constraints.Range(min=0)
            ]
        ),
        POLICIES: properties.Schema(
            properties.Schema.LIST,
            _('A list of policies to attach to this cluster.'),
            update_allowed=True,
            default=[],
            support_status=support.SupportStatus(version='8.0.0'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    P_POLICY: properties.Schema(
                        properties.Schema.STRING,
                        _("The name or ID of the policy."),
                        required=True,
                        constraints=[
                            constraints.CustomConstraint('senlin.policy')
                        ]
                    ),
                    P_ENABLED: properties.Schema(
                        properties.Schema.BOOLEAN,
                        _("Whether enable this policy on this cluster."),
                        default=True,
                    ),
                }
            )
        ),
    }

    attributes_schema = {
        ATTR_NAME: attributes.Schema(
            _("Cluster name."),
            type=attributes.Schema.STRING
        ),
        ATTR_METADATA: attributes.Schema(
            _("Cluster metadata."),
            type=attributes.Schema.MAP
        ),
        ATTR_DESIRED_CAPACITY: attributes.Schema(
            _("Desired capacity of the cluster."),
            type=attributes.Schema.INTEGER
        ),
        ATTR_NODES: attributes.Schema(
            _("Nodes list in the cluster."),
            type=attributes.Schema.LIST,
            cache_mode=attributes.Schema.CACHE_NONE
        ),
        ATTR_MIN_SIZE: attributes.Schema(
            _("Min size of the cluster."),
            type=attributes.Schema.INTEGER
        ),
        ATTR_MAX_SIZE: attributes.Schema(
            _("Max size of the cluster."),
            type=attributes.Schema.INTEGER
        ),
        ATTR_POLICIES: attributes.Schema(
            _("Policies attached to the cluster."),
            type=attributes.Schema.LIST,
            support_status=support.SupportStatus(version='8.0.0'),
        ),
        ATTR_COLLECT: attributes.Schema(
            _("Attributes collected from cluster. According to the jsonpath "
              "following this attribute, it will return a list of attributes "
              "collected from the nodes of this cluster."),
            type=attributes.Schema.LIST,
            support_status=support.SupportStatus(version='8.0.0'),
            cache_mode=attributes.Schema.CACHE_NONE
        )
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
                translation_path=[self.POLICIES, self.P_POLICY],
                client_plugin=self.client_plugin(),
                finder='get_policy_id'),
        ]
        return rules

    def handle_create(self):
        actions = []
        params = {
            'name': (self.properties[self.NAME] or
                     self.physical_resource_name()),
            'profile_id': self.properties[self.PROFILE],
            'desired_capacity': self.properties[self.DESIRED_CAPACITY],
            'min_size': self.properties[self.MIN_SIZE],
            'max_size': self.properties[self.MAX_SIZE],
            'metadata': self.properties[self.METADATA],
            'timeout': self.properties[self.TIMEOUT]
        }

        cluster = self.client().create_cluster(**params)
        action_id = cluster.location.split('/')[-1]
        self.resource_id_set(cluster.id)
        # for cluster creation, we just to check the action status
        # the action is executed above
        action = {
            'action_id': action_id,
            'done': False,
        }
        actions.append(action)
        if self.properties[self.POLICIES]:
            for p in self.properties[self.POLICIES]:
                params = {
                    'cluster': cluster.id,
                    'policy': p[self.P_POLICY],
                    'enabled': p[self.P_ENABLED],
                }
                action = {
                    'func': 'cluster_attach_policy',
                    'params': params,
                    'action_id': None,
                    'done': False,
                }
                actions.append(action)
        return actions

    def check_create_complete(self, actions):
        return self.client_plugin().execute_actions(actions)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client().delete_cluster(self.resource_id)
        return self.resource_id

    def check_delete_complete(self, resource_id):
        if not resource_id:
            return True

        try:
            self.client().get_cluster(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            return True
        return False

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        UPDATE_PROPS = (self.NAME, self.METADATA, self.TIMEOUT, self.PROFILE)
        RESIZE_PROPS = (self.MIN_SIZE, self.MAX_SIZE, self.DESIRED_CAPACITY)
        actions = []
        if not prop_diff:
            return actions
        cluster_obj = self.client().get_cluster(self.resource_id)
        # Update Policies
        if self.POLICIES in prop_diff:
            old_policies = self.properties[self.POLICIES]
            new_policies = prop_diff[self.POLICIES]
            old_policy_ids = [p[self.P_POLICY] for p in old_policies]
            update_policies = [p for p in new_policies
                               if p[self.P_POLICY] in old_policy_ids]
            update_policy_ids = [p[self.P_POLICY] for p in update_policies]
            add_policies = [p for p in new_policies
                            if p[self.P_POLICY] not in old_policy_ids]
            remove_policies = [p for p in old_policies
                               if p[self.P_POLICY] not in update_policy_ids]
            for p in update_policies:
                params = {
                    'policy': p[self.P_POLICY],
                    'cluster': self.resource_id,
                    'enabled': p[self.P_ENABLED]
                }
                action = {
                    'func': 'cluster_update_policy',
                    'params': params,
                    'action_id': None,
                    'done': False,
                }
                actions.append(action)
            for p in remove_policies:
                params = {
                    'policy': p[self.P_POLICY],
                    'cluster': self.resource_id,
                    'enabled': p[self.P_ENABLED]
                }
                action = {
                    'func': 'cluster_detach_policy',
                    'params': params,
                    'action_id': None,
                    'done': False,
                }
                actions.append(action)
            for p in add_policies:
                params = {
                    'policy': p[self.P_POLICY],
                    'cluster': self.resource_id,
                    'enabled': p[self.P_ENABLED]
                }
                action = {
                    'func': 'cluster_attach_policy',
                    'params': params,
                    'action_id': None,
                    'done': False,
                }
                actions.append(action)
        # Update cluster
        if any(p in prop_diff for p in UPDATE_PROPS):
            params = dict((k, v) for k, v in six.iteritems(prop_diff)
                          if k in UPDATE_PROPS)
            params['cluster'] = cluster_obj
            if self.PROFILE in params:
                params['profile_id'] = params.pop(self.PROFILE)
            action = {
                'func': 'update_cluster',
                'params': params,
                'action_id': None,
                'done': False,
            }
            actions.append(action)
        # Resize Cluster
        if any(p in prop_diff for p in RESIZE_PROPS):
            params = dict((k, v) for k, v in six.iteritems(prop_diff)
                          if k in RESIZE_PROPS)
            if self.DESIRED_CAPACITY in params:
                params['adjustment_type'] = 'EXACT_CAPACITY'
                params['number'] = params.pop(self.DESIRED_CAPACITY)
            params['cluster'] = self.resource_id
            action = {
                'func': 'cluster_resize',
                'params': params,
                'action_id': None,
                'done': False,
            }
            actions.append(action)
        return actions

    def check_update_complete(self, actions):
        return self.client_plugin().execute_actions(actions)

    def validate(self):
        min_size = self.properties[self.MIN_SIZE]
        max_size = self.properties[self.MAX_SIZE]
        desired_capacity = self.properties[self.DESIRED_CAPACITY]

        if max_size != -1 and max_size < min_size:
            msg = _("%(min_size)s can not be greater than %(max_size)s") % {
                'min_size': self.MIN_SIZE,
                'max_size': self.MAX_SIZE,
            }
            raise exception.StackValidationFailed(message=msg)

        if (desired_capacity < min_size or
                (max_size != -1 and desired_capacity > max_size)):
            msg = _("%(desired_capacity)s must be between %(min_size)s "
                    "and %(max_size)s") % {
                'desired_capacity': self.DESIRED_CAPACITY,
                'min_size': self.MIN_SIZE,
                'max_size': self.MAX_SIZE,
            }
            raise exception.StackValidationFailed(message=msg)

    def get_attribute(self, key, *path):
        if self.resource_id is None:
            return None

        if key == self.ATTR_COLLECT:
            if not path:
                raise exception.InvalidTemplateAttribute(
                    resource=self.name, key=key)
            attrs = self.client().collect_cluster_attrs(
                self.resource_id, path[0])
            attr = [attr.attr_value for attr in attrs]
            return attributes.select_from_attribute(attr, path[1:])
        else:
            return super(Cluster, self).get_attribute(key, *path)

    def _show_resource(self):
        cluster_dict = super(Cluster, self)._show_resource()
        cluster_dict[self.ATTR_POLICIES] = self.client().cluster_policies(
            self.resource_id)
        return cluster_dict

    def parse_live_resource_data(self, resource_properties, resource_data):
        reality = {}

        for key in self._update_allowed_properties:
            if key == self.PROFILE:
                value = resource_data.get('profile_id')
            elif key == self.POLICIES:
                value = []
                for p in resource_data.get(self.POLICIES):
                    v = {
                        'policy': p.get('policy_id'),
                        'enabled': p.get('enabled'),
                    }
                    value.append(v)
            else:
                value = resource_data.get(key)
            reality.update({key: value})

        return reality


def resource_mapping():
    return {
        'OS::Senlin::Cluster': Cluster
    }
