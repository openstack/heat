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
from heat.engine import resource
from heat.engine import support


class Cluster(resource.Resource):
    """A resource that creates a Senlin Cluster.

    Cluster resource in senlin can create and manage objects of
    the same nature, e.g. Nova servers, Heat stacks, Cinder volumes, etc.
    The collection of these objects is referred to as a cluster.
    """

    support_status = support.SupportStatus(version='6.0.0')

    default_client_name = 'senlin'

    PROPERTIES = (
        NAME, PROFILE, DESIRED_CAPACITY, MIN_SIZE, MAX_SIZE,
        METADATA, TIMEOUT
    ) = (
        'name', 'profile', 'desired_capacity', 'min_size', 'max_size',
        'metadata', 'timeout'
    )

    ATTRIBUTES = (
        ATTR_NAME, ATTR_METADATA, ATTR_NODES, ATTR_DESIRED_CAPACITY,
        ATTR_MIN_SIZE, ATTR_MAX_SIZE,
    ) = (
        "name", 'metadata', 'nodes', 'desired_capacity',
        'min_size', 'max_size'
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
        ),
        TIMEOUT: properties.Schema(
            properties.Schema.INTEGER,
            _('The number of seconds to wait for the cluster actions.'),
            update_allowed=True,
            constraints=[
                constraints.Range(min=0)
            ]
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
            type=attributes.Schema.LIST
        ),
        ATTR_MIN_SIZE: attributes.Schema(
            _("Min size of the cluster."),
            type=attributes.Schema.INTEGER
        ),
        ATTR_MAX_SIZE: attributes.Schema(
            _("Max size of the cluster."),
            type=attributes.Schema.INTEGER
        ),
    }

    def handle_create(self):
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
        return action_id

    def check_create_complete(self, action_id):
        return self.client_plugin().check_action_status(action_id)

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
        updaters = {}
        if prop_diff:
            if any(p in prop_diff for p in UPDATE_PROPS):
                params = dict((k, v) for k, v in six.iteritems(prop_diff)
                              if k in UPDATE_PROPS)
                if self.PROFILE in prop_diff:
                    params.pop(self.PROFILE)
                    params['profile_id'] = prop_diff[self.PROFILE]
                    updaters['cluster_update'] = {
                        'params': params,
                        'start': False,
                    }
            if any(p in prop_diff for p in RESIZE_PROPS):
                params = dict((k, v) for k, v in six.iteritems(prop_diff)
                              if k in RESIZE_PROPS)
                if self.DESIRED_CAPACITY in prop_diff:
                    params.pop(self.DESIRED_CAPACITY)
                    params['adjustment_type'] = 'EXACT_CAPACITY'
                    params['number'] = prop_diff.pop(self.DESIRED_CAPACITY)
                updaters['cluster_resize'] = {
                    'params': params,
                    'start': False,
                }
            return updaters

    def check_update_complete(self, updaters):
        def start_action(action, params):
            if action == 'cluster_resize':
                resp = self.client().cluster_resize(self.resource_id,
                                                    **params)
                return resp['action']
            elif action == 'cluster_update':
                resp = self.client().update_cluster(self.resource_id,
                                                    **params)
                return resp.location.split('/')[-1]

        if not updaters:
            return True
        for k, updater in list(updaters.items()):
            if not updater['start']:
                action_id = start_action(k, updater['params'])
                updater['action'] = action_id
                updater['start'] = True
            else:
                ret = self.client_plugin().check_action_status(
                    updater['action'])
                if ret:
                    del updaters[k]
            return False

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

    def _resolve_attribute(self, name):
        cluster = self.client().get_cluster(self.resource_id)
        return getattr(cluster, name, None)

    def _show_resource(self):
        cluster = self.client().get_cluster(self.resource_id)
        return cluster.to_dict()


def resource_mapping():
    return {
        'OS::Senlin::Cluster': Cluster
    }
