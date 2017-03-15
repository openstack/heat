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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import translation


class Cluster(resource.Resource):
    """A resource that creates a magnum cluster.

    This resource creates a magnum cluster, which is a
    collection of node objects where work is scheduled.
    """

    support_status = support.SupportStatus(version='9.0.0')

    default_client_name = 'magnum'

    entity = 'clusters'

    PROPERTIES = (
        NAME, CLUSTER_TEMPLATE, KEYPAIR, NODE_COUNT, MASTER_COUNT,
        DISCOVERY_URL, CREATE_TIMEOUT
    ) = (
        'name', 'cluster_template', 'keypair', 'node_count', 'master_count',
        'discovery_url', 'create_timeout'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The cluster name.'),
        ),
        CLUSTER_TEMPLATE: properties.Schema(
            properties.Schema.STRING,
            _('The name or ID of the cluster template.'),
            constraints=[
                constraints.CustomConstraint('magnum.cluster_template')
            ],
            required=True
        ),
        KEYPAIR: properties.Schema(
            properties.Schema.STRING,
            _('The name of the keypair. If not presented, use keypair in '
              'cluster template.'),
            constraints=[
                constraints.CustomConstraint('nova.keypair')
            ]
        ),
        NODE_COUNT: properties.Schema(
            properties.Schema.INTEGER,
            _('The node count for this cluster.'),
            constraints=[constraints.Range(min=1)],
            update_allowed=True,
            default=1
        ),
        MASTER_COUNT: properties.Schema(
            properties.Schema.INTEGER,
            _('The number of master nodes for this cluster.'),
            constraints=[constraints.Range(min=1)],
            update_allowed=True,
            default=1
        ),
        DISCOVERY_URL: properties.Schema(
            properties.Schema.STRING,
            _('Specifies a custom discovery url for node discovery.'),
            update_allowed=True,
        ),
        CREATE_TIMEOUT: properties.Schema(
            properties.Schema.INTEGER,
            _('Timeout for creating the cluster in minutes. '
              'Set to 0 for no timeout.'),
            constraints=[constraints.Range(min=0)],
            update_allowed=True,
            default=60
        )
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.CLUSTER_TEMPLATE],
                client_plugin=self.client_plugin('magnum'),
                finder='get_cluster_template')
        ]

    def handle_create(self):
        args = dict(self.properties.items())

        args['cluster_template_id'] = self.properties[self.CLUSTER_TEMPLATE]
        del args[self.CLUSTER_TEMPLATE]
        cluster = self.client().clusters.create(**args)
        self.resource_id_set(cluster.uuid)
        return cluster.uuid

    def check_create_complete(self, id):
        cluster = self.client().clusters.get(id)
        if cluster.status == 'CREATE_IN_PROGRESS':
            return False
        elif cluster.status == 'CREATE_COMPLETE':
            return True
        elif cluster.status == 'CREATE_FAILED':
            msg = (_("Failed to create Cluster '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': cluster.status_reason})
            raise exception.ResourceInError(status_reason=msg,
                                            resource_status=cluster.status)
        else:
            msg = (_("Unknown status creating Cluster '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': cluster.status_reason})
            raise exception.ResourceUnknownStatus(
                status_reason=msg, resource_status=cluster.status)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            patch = [{'op': 'replace', 'path': '/' + k, 'value': v}
                     for k, v in six.iteritems(prop_diff)]
            self.client().clusters.update(self.resource_id, patch)
            return self.resource_id

    def check_update_complete(self, id):
        cluster = self.client().clusters.get(id)
        if cluster.status == 'UPDATE_IN_PROGRESS':
            return False
        elif cluster.status == 'UPDATE_COMPLETE':
            return True
        elif cluster.status == 'UPDATE_FAILED':
            msg = (_("Failed to update Cluster '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': cluster.status_reason})
            raise exception.ResourceInError(
                status_reason=msg, resource_status=cluster.status)

        else:
            msg = (_("Unknown status updating Cluster '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': cluster.status_reason})
            raise exception.ResourceUnknownStatus(
                status_reason=msg, resource_status=cluster.status)

    def check_delete_complete(self, id):
        if not id:
            return True
        try:
            self.client().clusters.get(id)
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)
            return True
        return False


def resource_mapping():
    return {
        'OS::Magnum::Cluster': Cluster
    }
