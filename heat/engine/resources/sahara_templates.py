# Copyright (c) 2014 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)

#NOTE(pshchelo): copied from sahara/utils/api_validator.py
SAHARA_NAME_REGEX = (r"^(([a-zA-Z]|[a-zA-Z][a-zA-Z0-9\-]"
                     r"*[a-zA-Z0-9])\.)*([A-Za-z]|[A-Za-z]"
                     r"[A-Za-z0-9\-]*[A-Za-z0-9])$")


class SaharaNodeGroupTemplate(resource.Resource):

    PROPERTIES = (
        NAME, PLUGIN_NAME, HADOOP_VERSION, FLAVOR,
        DESCRIPTION, VOLUMES_PER_NODE, VOLUMES_SIZE,
        NODE_PROCESSES, FLOATING_IP_POOL, NODE_CONFIGS,
    ) = (
        'name', 'plugin_name', 'hadoop_version', 'flavor',
        'description', 'volumes_per_node', 'volumes_size',
        'node_processes', 'floating_ip_pool', 'node_configs',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _("Name for the Sahara Node Group Template."),
            constraints=[
                constraints.Length(min=1, max=50),
                constraints.AllowedPattern(SAHARA_NAME_REGEX),
            ],
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the Node Group Template.'),
            default="",
        ),
        PLUGIN_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Plugin name.'),
            required=True,
        ),
        HADOOP_VERSION: properties.Schema(
            properties.Schema.STRING,
            _('Version of Hadoop running on instances.'),
            required=True,
        ),
        FLAVOR: properties.Schema(
            properties.Schema.STRING,
            _('Name or ID Nova flavor for the nodes.'),
            required=True,
        ),
        VOLUMES_PER_NODE: properties.Schema(
            properties.Schema.INTEGER,
            _("Volumes per node."),
            constraints=[
                constraints.Range(min=0),
            ],
        ),
        VOLUMES_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _("Size of the volumes, in GB."),
            constraints=[
                constraints.Range(min=1),
            ],
        ),
        NODE_PROCESSES: properties.Schema(
            properties.Schema.LIST,
            _("List of processes to run on every node."),
            required=True,
            constraints=[
                constraints.Length(min=1),
            ],
            schema=properties.Schema(
                properties.Schema.STRING,
            ),
        ),
        FLOATING_IP_POOL: properties.Schema(
            properties.Schema.STRING,
            _("Name or UUID of the Neutron floating IP network to use."),
            constraints=[
                constraints.CustomConstraint('neutron.network'),
            ],
        ),
        NODE_CONFIGS: properties.Schema(
            properties.Schema.MAP,
            _("Dictionary of node configurations."),
        ),
    }

    default_client_name = 'sahara'

    physical_resource_name_limit = 50

    def _ngt_name(self):
        name = self.properties.get(self.NAME)
        if name:
            return name
        return self.physical_resource_name()

    def handle_create(self):
        plugin_name = self.properties[self.PLUGIN_NAME]
        hadoop_version = self.properties[self.HADOOP_VERSION]
        node_processes = self.properties[self.NODE_PROCESSES]
        description = self.properties[self.DESCRIPTION]
        flavor_id = self.client_plugin("nova").get_flavor_id(
            self.properties[self.FLAVOR])
        volumes_per_node = self.properties.get(self.VOLUMES_PER_NODE)
        volumes_size = self.properties.get(self.VOLUMES_SIZE)
        floating_ip_pool = self.properties.get(self.FLOATING_IP_POOL)
        if floating_ip_pool:
            floating_ip_pool = self.client_plugin(
                'neutron').find_neutron_resource(self.properties,
                                                 self.FLOATING_IP_POOL,
                                                 'network')
        node_configs = self.properties.get(self.NODE_CONFIGS)

        node_group_template = self.client().node_group_templates.create(
            self._ngt_name(),
            plugin_name, hadoop_version, flavor_id,
            description=description,
            volumes_per_node=volumes_per_node,
            volumes_size=volumes_size,
            node_processes=node_processes,
            floating_ip_pool=floating_ip_pool,
            node_configs=node_configs)
        LOG.info(_("Node Group Template '%s' has been created"
                   ) % node_group_template.name)
        self.resource_id_set(node_group_template.id)
        return self.resource_id

    def handle_delete(self):
        if not self.resource_id:
            return
        try:
            self.client().node_group_templates.delete(
                self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        LOG.info(_("Node Group Template '%s' has been deleted."
                   ) % self._ngt_name())

    def validate(self):
        res = super(SaharaNodeGroupTemplate, self).validate()
        if res:
            return res
        #NOTE(pshchelo): floating ip pool must be set for Neutron
        if (self.is_using_neutron() and
                not self.properties.get(self.FLOATING_IP_POOL)):
            msg = _("%s must be provided.") % self.FLOATING_IP_POOL
            raise exception.StackValidationFailed(message=msg)


class SaharaClusterTemplate(resource.Resource):

    PROPERTIES = (
        NAME, PLUGIN_NAME, HADOOP_VERSION, DESCRIPTION,
        ANTI_AFFINITY, MANAGEMENT_NETWORK,
        CLUSTER_CONFIGS, NODE_GROUPS, IMAGE_ID,
    ) = (
        'name', 'plugin_name', 'hadoop_version', 'description',
        'anti_affinity', 'neutron_management_network',
        'cluster_configs', 'node_groups', 'default_image_id',
    )

    _NODE_GROUP_KEYS = (
        NG_NAME, COUNT, NG_TEMPLATE_ID,
    ) = (
        'name', 'count', 'node_group_template_id',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _("Name for the Sahara Cluster Template."),
            constraints=[
                constraints.Length(min=1, max=50),
                constraints.AllowedPattern(SAHARA_NAME_REGEX),
            ],
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the Sahara Group Template.'),
            default="",
        ),
        PLUGIN_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Plugin name.'),
            required=True,
        ),
        HADOOP_VERSION: properties.Schema(
            properties.Schema.STRING,
            _('Version of Hadoop running on instances.'),
            required=True,
        ),
        IMAGE_ID: properties.Schema(
            properties.Schema.STRING,
            _("ID of the default image to use for the template."),
            constraints=[
                constraints.CustomConstraint('glance.image')
            ],
        ),
        MANAGEMENT_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('Name or UUID of Neutron network.'),
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ],
        ),
        ANTI_AFFINITY: properties.Schema(
            properties.Schema.LIST,
            _("List of processes to enable anti-affinity for."),
            schema=properties.Schema(
                properties.Schema.STRING,
            ),
        ),
        CLUSTER_CONFIGS: properties.Schema(
            properties.Schema.MAP,
            _('Cluster configs dictionary.'),
        ),
        NODE_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('Node groups.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    NG_NAME: properties.Schema(
                        properties.Schema.STRING,
                        _('Name of the Node group.'),
                        required=True
                    ),
                    COUNT: properties.Schema(
                        properties.Schema.INTEGER,
                        _("Number of instances in the Node group."),
                        required=True,
                        constraints=[
                            constraints.Range(min=1)
                        ]
                    ),
                    NG_TEMPLATE_ID: properties.Schema(
                        properties.Schema.STRING,
                        _("ID of the Node Group Template."),
                        required=True
                    ),
                }
            ),

        ),
    }

    default_client_name = 'sahara'

    physical_resource_name_limit = 50

    def _cluster_template_name(self):
        name = self.properties.get(self.NAME)
        if name:
            return name
        return self.physical_resource_name()

    def handle_create(self):
        plugin_name = self.properties[self.PLUGIN_NAME]
        hadoop_version = self.properties[self.HADOOP_VERSION]
        description = self.properties.get(self.DESCRIPTION)
        image_id = self.properties.get(self.IMAGE_ID)
        net_id = self.properties.get(self.MANAGEMENT_NETWORK)
        if net_id:
            net_id = self.client_plugin('neutron').find_neutron_resource(
                self.properties, self.MANAGEMENT_NETWORK, 'network')
        anti_affinity = self.properties.get(self.ANTI_AFFINITY)
        cluster_configs = self.properties.get(self.CLUSTER_CONFIGS)
        node_groups = self.properties.get(self.NODE_GROUPS)
        cluster_template = self.client().cluster_templates.create(
            self._cluster_template_name(),
            plugin_name, hadoop_version,
            description=description,
            default_image_id=image_id,
            anti_affinity=anti_affinity,
            net_id=net_id,
            cluster_configs=cluster_configs,
            node_groups=node_groups
        )
        LOG.info(_("Cluster Template '%s' has been created"
                   ) % cluster_template.name)
        self.resource_id_set(cluster_template.id)
        return self.resource_id

    def handle_delete(self):
        if not self.resource_id:
            return
        try:
            self.client().cluster_templates.delete(
                self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        LOG.info(_("Cluster Template '%s' has been deleted."
                   ) % self._cluster_template_name())

    def validate(self):
        res = super(SaharaClusterTemplate, self).validate()
        if res:
            return res
        # check if running on neutron and MANAGEMENT_NETWORK missing
        #NOTE(pshchelo): on nova-network with MANAGEMENT_NETWORK present
        # overall stack validation will fail due to neutron.network constraint,
        # although the message will be not really relevant.
        if (self.is_using_neutron() and
                not self.properties.get(self.MANAGEMENT_NETWORK)):
            msg = _("%s must be provided"
                    ) % self.MANAGEMENT_NETWORK
            raise exception.StackValidationFailed(message=msg)


def resource_mapping():
    return {
        'OS::Sahara::NodeGroupTemplate': SaharaNodeGroupTemplate,
        'OS::Sahara::ClusterTemplate': SaharaClusterTemplate,
    }
