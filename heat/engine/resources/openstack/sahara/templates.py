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

import re
import six

from oslo_log import log as logging
from oslo_utils import encodeutils

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import support
from heat.engine import translation

LOG = logging.getLogger(__name__)

# NOTE(pshchelo): copied from sahara/utils/api_validator.py
SAHARA_NAME_REGEX = (r"^(([a-zA-Z]|[a-zA-Z][a-zA-Z0-9\-]"
                     r"*[a-zA-Z0-9])\.)*([A-Za-z]|[A-Za-z]"
                     r"[A-Za-z0-9\-]*[A-Za-z0-9])$")


class SaharaNodeGroupTemplate(resource.Resource):
    """A resource for managing Sahara node group templates.

    A Node Group Template describes a group of nodes within cluster. It
    contains a list of hadoop processes that will be launched on each instance
    in a group. Also a Node Group Template may provide node scoped
    configurations for those processes.
    """

    support_status = support.SupportStatus(version='2014.2')

    PROPERTIES = (
        NAME, PLUGIN_NAME, HADOOP_VERSION, FLAVOR, DESCRIPTION,
        VOLUMES_PER_NODE, VOLUMES_SIZE, VOLUME_TYPE,
        SECURITY_GROUPS, AUTO_SECURITY_GROUP,
        AVAILABILITY_ZONE, VOLUMES_AVAILABILITY_ZONE,
        NODE_PROCESSES, FLOATING_IP_POOL, NODE_CONFIGS, IMAGE_ID,
        IS_PROXY_GATEWAY, VOLUME_LOCAL_TO_INSTANCE, USE_AUTOCONFIG,
        SHARES

    ) = (
        'name', 'plugin_name', 'hadoop_version', 'flavor', 'description',
        'volumes_per_node', 'volumes_size', 'volume_type',
        'security_groups', 'auto_security_group',
        'availability_zone', 'volumes_availability_zone',
        'node_processes', 'floating_ip_pool', 'node_configs', 'image_id',
        'is_proxy_gateway', 'volume_local_to_instance', 'use_autoconfig',
        'shares'
    )

    _SHARE_KEYS = (
        SHARE_ID, PATH, ACCESS_LEVEL
    ) = (
        'id', 'path', 'access_level'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _("Name for the Sahara Node Group Template."),
            constraints=[
                constraints.Length(min=1, max=50),
                constraints.AllowedPattern(SAHARA_NAME_REGEX),
            ],
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the Node Group Template.'),
            default="",
            update_allowed=True
        ),
        PLUGIN_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Plugin name.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('sahara.plugin')
            ],
            update_allowed=True
        ),
        HADOOP_VERSION: properties.Schema(
            properties.Schema.STRING,
            _('Version of Hadoop running on instances.'),
            required=True,
            update_allowed=True
        ),
        FLAVOR: properties.Schema(
            properties.Schema.STRING,
            _('Name or ID Nova flavor for the nodes.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('nova.flavor')
            ],
            update_allowed=True
        ),
        VOLUMES_PER_NODE: properties.Schema(
            properties.Schema.INTEGER,
            _("Volumes per node."),
            constraints=[
                constraints.Range(min=0),
            ],
            default=0,
            update_allowed=True
        ),
        VOLUMES_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _("Size of the volumes, in GB."),
            constraints=[
                constraints.Range(min=1),
            ],
            update_allowed=True
        ),
        VOLUME_TYPE: properties.Schema(
            properties.Schema.STRING,
            _("Type of the volume to create on Cinder backend."),
            constraints=[
                constraints.CustomConstraint('cinder.vtype')
            ],
            update_allowed=True
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _("List of security group names or IDs to assign to this "
              "Node Group template."),
            schema=properties.Schema(
                properties.Schema.STRING,
            ),
            update_allowed=True
        ),
        AUTO_SECURITY_GROUP: properties.Schema(
            properties.Schema.BOOLEAN,
            _("Defines whether auto-assign security group to this "
              "Node Group template."),
            update_allowed=True
        ),
        AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _("Availability zone to create servers in."),
            update_allowed=True
        ),
        VOLUMES_AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _("Availability zone to create volumes in."),
            update_allowed=True
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
            update_allowed=True
        ),
        FLOATING_IP_POOL: properties.Schema(
            properties.Schema.STRING,
            _("Name or UUID of the Neutron floating IP network or "
              "name of the Nova floating ip pool to use. "
              "Should not be provided when used with Nova-network "
              "that auto-assign floating IPs."),
            update_allowed=True
        ),
        NODE_CONFIGS: properties.Schema(
            properties.Schema.MAP,
            _("Dictionary of node configurations."),
            update_allowed=True
        ),
        IMAGE_ID: properties.Schema(
            properties.Schema.STRING,
            _("ID of the image to use for the template."),
            constraints=[
                constraints.CustomConstraint('sahara.image'),
            ],
            update_allowed=True
        ),
        IS_PROXY_GATEWAY: properties.Schema(
            properties.Schema.BOOLEAN,
            _("Provide access to nodes using other nodes of the cluster "
              "as proxy gateways."),
            support_status=support.SupportStatus(version='5.0.0'),
            update_allowed=True
        ),
        VOLUME_LOCAL_TO_INSTANCE: properties.Schema(
            properties.Schema.BOOLEAN,
            _("Create volumes on the same physical port as an instance."),
            support_status=support.SupportStatus(version='5.0.0'),
            update_allowed=True
        ),
        USE_AUTOCONFIG: properties.Schema(
            properties.Schema.BOOLEAN,
            _("Configure most important configs automatically."),
            support_status=support.SupportStatus(version='5.0.0'),
            update_allowed=True
        ),
        SHARES: properties.Schema(
            properties.Schema.LIST,
            _("List of manila shares to be mounted."),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    SHARE_ID: properties.Schema(
                        properties.Schema.STRING,
                        _("Id of the manila share."),
                        required=True
                    ),
                    PATH: properties.Schema(
                        properties.Schema.STRING,
                        _("Local path on each cluster node on which to mount "
                          "the share. Defaults to '/mnt/{share_id}'.")
                    ),
                    ACCESS_LEVEL: properties.Schema(
                        properties.Schema.STRING,
                        _("Governs permissions set in manila for the cluster "
                          "ips."),
                        constraints=[
                            constraints.AllowedValues(['rw', 'ro']),
                        ],
                        default='rw'
                    )
                }
            ),
            support_status=support.SupportStatus(version='6.0.0'),
            update_allowed=True
        )
    }

    default_client_name = 'sahara'

    physical_resource_name_limit = 50

    entity = 'node_group_templates'

    def translation_rules(self, props):
        neutron_client_plugin = self.client_plugin('neutron')
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.FLAVOR],
                client_plugin=self.client_plugin('nova'),
                finder='find_flavor_by_name_or_id'),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.FLOATING_IP_POOL],
                client_plugin=neutron_client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=neutron_client_plugin.RES_TYPE_NETWORK)
            ]

    def _ngt_name(self, name):
        if name:
            return name
        return re.sub('[^a-zA-Z0-9-]', '', self.physical_resource_name())

    def _prepare_properties(self, props):
        """Prepares the property values."""
        if self.NAME in props:
            props['name'] = self._ngt_name(props[self.NAME])
        if self.FLAVOR in props:
            props['flavor_id'] = props.pop(self.FLAVOR)
        return props

    def handle_create(self):
        props = dict((k, v) for k, v in six.iteritems(self.properties))
        args = self._prepare_properties(props)
        node_group_template = self.client().node_group_templates.create(**args)
        LOG.info("Node Group Template '%s' has been created",
                 node_group_template.name)
        self.resource_id_set(node_group_template.id)
        return self.resource_id

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            args = self._prepare_properties(prop_diff)
            self.client().node_group_templates.update(self.resource_id, **args)

    def validate(self):
        res = super(SaharaNodeGroupTemplate, self).validate()
        if res:
            return res
        pool = self.properties[self.FLOATING_IP_POOL]
        if pool:
            if self.is_using_neutron():
                neutron_client_plugin = self.client_plugin('neutron')
                try:
                    neutron_client_plugin.find_resourceid_by_name_or_id(
                        neutron_client_plugin.RES_TYPE_NETWORK,
                        pool)
                except Exception as ex:
                    if (neutron_client_plugin.is_not_found(ex)
                            or neutron_client_plugin.is_no_unique(ex)):
                        err_msg = encodeutils.exception_to_unicode(ex)
                        raise exception.StackValidationFailed(message=err_msg)
                    raise

            else:
                try:
                    self.client('nova').floating_ip_pools.find(name=pool)
                except Exception as ex:
                    if self.client_plugin('nova').is_not_found(ex):
                        err_msg = encodeutils.exception_to_unicode(ex)
                        raise exception.StackValidationFailed(message=err_msg)
                    raise

        self.client_plugin().validate_hadoop_version(
            self.properties[self.PLUGIN_NAME],
            self.properties[self.HADOOP_VERSION]
        )

        # validate node processes
        plugin = self.client().plugins.get_version_details(
            self.properties[self.PLUGIN_NAME],
            self.properties[self.HADOOP_VERSION])
        allowed_processes = [item for sublist in
                             list(six.itervalues(plugin.node_processes))
                             for item in sublist]
        unsupported_processes = []
        for process in self.properties[self.NODE_PROCESSES]:
            if process not in allowed_processes:
                unsupported_processes.append(process)
        if unsupported_processes:
            msg = (_("Plugin %(plugin)s doesn't support the following "
                     "node processes: %(unsupported)s. Allowed processes are: "
                     "%(allowed)s") %
                   {'plugin': self.properties[self.PLUGIN_NAME],
                    'unsupported': ', '.join(unsupported_processes),
                    'allowed': ', '.join(allowed_processes)})
            raise exception.StackValidationFailed(
                path=[self.stack.t.RESOURCES,
                      self.name,
                      self.stack.t.get_section_name(rsrc_defn.PROPERTIES)],
                message=msg)

    def parse_live_resource_data(self, resource_properties, resource_data):
        result = super(SaharaNodeGroupTemplate, self).parse_live_resource_data(
            resource_properties, resource_data)

        for group in result[self.SHARES] or []:
            remove_keys = set(group.keys()) - set(self._SHARE_KEYS)
            for key in remove_keys:
                del group[key]
        result[self.FLAVOR] = resource_data.get('flavor_id')
        return result


class SaharaClusterTemplate(resource.Resource):
    """A resource for managing Sahara cluster templates.

    A Cluster Template is designed to bring Node Group Templates together to
    form a Cluster. A Cluster Template defines what Node Groups will be
    included and how many instances will be created in each. Some data
    processing framework configurations can not be applied to a single node,
    but to a whole Cluster. A user can specify these kinds of configurations in
    a Cluster Template. Sahara enables users to specify which processes should
    be added to an anti-affinity group within a Cluster Template. If a process
    is included into an anti-affinity group, it means that VMs where this
    process is going to be launched should be scheduled to different hardware
    hosts.
    """

    support_status = support.SupportStatus(version='2014.2')

    PROPERTIES = (
        NAME, PLUGIN_NAME, HADOOP_VERSION, DESCRIPTION,
        ANTI_AFFINITY, MANAGEMENT_NETWORK,
        CLUSTER_CONFIGS, NODE_GROUPS, IMAGE_ID, USE_AUTOCONFIG,
        SHARES
    ) = (
        'name', 'plugin_name', 'hadoop_version', 'description',
        'anti_affinity', 'neutron_management_network',
        'cluster_configs', 'node_groups', 'default_image_id', 'use_autoconfig',
        'shares'
    )

    _NODE_GROUP_KEYS = (
        NG_NAME, COUNT, NG_TEMPLATE_ID,
    ) = (
        'name', 'count', 'node_group_template_id',
    )

    _SHARE_KEYS = (
        SHARE_ID, PATH, ACCESS_LEVEL
    ) = (
        'id', 'path', 'access_level'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _("Name for the Sahara Cluster Template."),
            constraints=[
                constraints.Length(min=1, max=50),
                constraints.AllowedPattern(SAHARA_NAME_REGEX),
            ],
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the Sahara Group Template.'),
            default="",
            update_allowed=True
        ),
        PLUGIN_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Plugin name.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('sahara.plugin')
            ],
            update_allowed=True
        ),
        HADOOP_VERSION: properties.Schema(
            properties.Schema.STRING,
            _('Version of Hadoop running on instances.'),
            required=True,
            update_allowed=True
        ),
        IMAGE_ID: properties.Schema(
            properties.Schema.STRING,
            _("ID of the default image to use for the template."),
            constraints=[
                constraints.CustomConstraint('sahara.image'),
            ],
            update_allowed=True
        ),
        MANAGEMENT_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('Name or UUID of network.'),
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ],
            update_allowed=True
        ),
        ANTI_AFFINITY: properties.Schema(
            properties.Schema.LIST,
            _("List of processes to enable anti-affinity for."),
            schema=properties.Schema(
                properties.Schema.STRING,
            ),
            update_allowed=True
        ),
        CLUSTER_CONFIGS: properties.Schema(
            properties.Schema.MAP,
            _('Cluster configs dictionary.'),
            update_allowed=True
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
            update_allowed=True
        ),
        USE_AUTOCONFIG: properties.Schema(
            properties.Schema.BOOLEAN,
            _("Configure most important configs automatically."),
            support_status=support.SupportStatus(version='5.0.0')
        ),
        SHARES: properties.Schema(
            properties.Schema.LIST,
            _("List of manila shares to be mounted."),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    SHARE_ID: properties.Schema(
                        properties.Schema.STRING,
                        _("Id of the manila share."),
                        required=True
                    ),
                    PATH: properties.Schema(
                        properties.Schema.STRING,
                        _("Local path on each cluster node on which to mount "
                          "the share. Defaults to '/mnt/{share_id}'.")
                    ),
                    ACCESS_LEVEL: properties.Schema(
                        properties.Schema.STRING,
                        _("Governs permissions set in manila for the cluster "
                          "ips."),
                        constraints=[
                            constraints.AllowedValues(['rw', 'ro']),
                        ],
                        default='rw'
                    )
                }
            ),
            support_status=support.SupportStatus(version='6.0.0'),
            update_allowed=True
        )
    }

    default_client_name = 'sahara'

    physical_resource_name_limit = 50

    entity = 'cluster_templates'

    def translation_rules(self, props):
        neutron_client_plugin = self.client_plugin('neutron')
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.MANAGEMENT_NETWORK],
                client_plugin=neutron_client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=neutron_client_plugin.RES_TYPE_NETWORK)
        ]

    def _cluster_template_name(self, name):
        if name:
            return name
        return re.sub('[^a-zA-Z0-9-]', '', self.physical_resource_name())

    def _prepare_properties(self, props):
        """Prepares the property values."""
        if self.NAME in props:
            props['name'] = self._cluster_template_name(props[self.NAME])
        if self.MANAGEMENT_NETWORK in props:
            props['net_id'] = props.pop(self.MANAGEMENT_NETWORK)
        return props

    def handle_create(self):
        props = dict((k, v) for k, v in six.iteritems(self.properties))
        args = self._prepare_properties(props)
        cluster_template = self.client().cluster_templates.create(**args)
        LOG.info("Cluster Template '%s' has been created",
                 cluster_template.name)
        self.resource_id_set(cluster_template.id)
        return self.resource_id

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            args = self._prepare_properties(prop_diff)
            self.client().cluster_templates.update(self.resource_id, **args)

    def validate(self):
        res = super(SaharaClusterTemplate, self).validate()
        if res:
            return res
        # check if running on neutron and MANAGEMENT_NETWORK missing
        if (self.is_using_neutron() and
                not self.properties[self.MANAGEMENT_NETWORK]):
            msg = _("%s must be provided"
                    ) % self.MANAGEMENT_NETWORK
            raise exception.StackValidationFailed(message=msg)

        self.client_plugin().validate_hadoop_version(
            self.properties[self.PLUGIN_NAME],
            self.properties[self.HADOOP_VERSION]
        )

    def parse_live_resource_data(self, resource_properties, resource_data):
        result = super(SaharaClusterTemplate, self).parse_live_resource_data(
            resource_properties, resource_data)

        for group in result[self.NODE_GROUPS] or []:
            remove_keys = set(group.keys()) - set(self._NODE_GROUP_KEYS)
            for key in remove_keys:
                del group[key]
        for group in result[self.SHARES] or []:
            remove_keys = set(group.keys()) - set(self._SHARE_KEYS)
            for key in remove_keys:
                del group[key]
        return result


def resource_mapping():
    return {
        'OS::Sahara::NodeGroupTemplate': SaharaNodeGroupTemplate,
        'OS::Sahara::ClusterTemplate': SaharaClusterTemplate,
    }
