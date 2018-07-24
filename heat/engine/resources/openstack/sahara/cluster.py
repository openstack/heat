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

from oslo_log import log as logging

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import translation

LOG = logging.getLogger(__name__)

# NOTE(jfreud, pshchelo): copied from sahara/utils/api_validator.py
SAHARA_NAME_REGEX = (r"^(([a-zA-Z]|[a-zA-Z][a-zA-Z0-9\-]"
                     r"*[a-zA-Z0-9])\.)*([A-Za-z]|[A-Za-z]"
                     r"[A-Za-z0-9\-]*[A-Za-z0-9])$")

# NOTE(jfreud): we do not use physical_resource_name_limit attr because we
# prefer to truncate _after_ removing invalid characters
SAHARA_CLUSTER_NAME_MAX_LENGTH = 80


class SaharaCluster(resource.Resource):
    """A resource for managing Sahara clusters.

    The Cluster entity represents a collection of VM instances that all have
    the same data processing framework installed. It is mainly characterized by
    a VM image with a pre-installed framework which will be used for cluster
    deployment. Users may choose one of the pre-configured Cluster Templates to
    start a Cluster. To get access to VMs after a Cluster has started, the user
    should specify a keypair.
    """

    PROPERTIES = (
        NAME, PLUGIN_NAME, HADOOP_VERSION, CLUSTER_TEMPLATE_ID,
        KEY_NAME, IMAGE, MANAGEMENT_NETWORK, IMAGE_ID,
        USE_AUTOCONFIG, SHARES
    ) = (
        'name', 'plugin_name', 'hadoop_version', 'cluster_template_id',
        'key_name', 'image', 'neutron_management_network', 'default_image_id',
        'use_autoconfig', 'shares'
    )

    _SHARE_KEYS = (
        SHARE_ID, PATH, ACCESS_LEVEL
    ) = (
        'id', 'path', 'access_level'
    )

    ATTRIBUTES = (
        STATUS, INFO,
    ) = (
        "status", "info",
    )

    CLUSTER_STATUSES = (
        CLUSTER_ACTIVE, CLUSTER_ERROR
    ) = (
        'Active', 'Error'
    )
    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Hadoop cluster name.'),
            constraints=[
                constraints.Length(min=1, max=SAHARA_CLUSTER_NAME_MAX_LENGTH),
                constraints.AllowedPattern(SAHARA_NAME_REGEX),
            ],
        ),
        PLUGIN_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Plugin name.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('sahara.plugin')
            ]
        ),
        HADOOP_VERSION: properties.Schema(
            properties.Schema.STRING,
            _('Version of Hadoop running on instances.'),
            required=True,
        ),
        CLUSTER_TEMPLATE_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of the Cluster Template used for '
              'Node Groups and configurations.'),
            constraints=[
                constraints.CustomConstraint('sahara.cluster_template')
            ],
            required=True
        ),
        KEY_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Keypair added to instances to make them accessible for user.'),
            constraints=[
                constraints.CustomConstraint('nova.keypair')
            ],
        ),
        IMAGE: properties.Schema(
            properties.Schema.STRING,
            _('Name or UUID of the image used to boot Hadoop nodes.'),
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='6.0.0',
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    message=_('Use property %s.') % IMAGE_ID,
                    version='2015.1',
                    previous_status=support.SupportStatus(version='2014.2'))
            ),
            constraints=[
                constraints.CustomConstraint('glance.image')
            ],
        ),
        IMAGE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Default name or UUID of the image used to boot Hadoop nodes.'),
            constraints=[
                constraints.CustomConstraint('sahara.image'),
            ],
            support_status=support.SupportStatus(version='2015.1')
        ),
        MANAGEMENT_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('Name or UUID of network.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ],
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
            support_status=support.SupportStatus(version='6.0.0')
        )
    }

    attributes_schema = {
        STATUS: attributes.Schema(
            _("Cluster status."),
            type=attributes.Schema.STRING
        ),
        INFO: attributes.Schema(
            _("Cluster information."),
            type=attributes.Schema.MAP
        ),
    }

    default_client_name = 'sahara'

    entity = 'clusters'

    def translation_rules(self, props):
        neutron_client_plugin = self.client_plugin('neutron')
        rules = [
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.IMAGE_ID],
                value_path=[self.IMAGE]),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.IMAGE_ID],
                client_plugin=self.client_plugin('glance'),
                finder='find_image_by_name_or_id'),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.MANAGEMENT_NETWORK],
                client_plugin=neutron_client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=neutron_client_plugin.RES_TYPE_NETWORK)
        ]
        return rules

    def _cluster_name(self):
        name = self.properties[self.NAME]
        if name:
            return name
        return self.reduce_physical_resource_name(
            re.sub('[^a-zA-Z0-9-]', '', self.physical_resource_name()),
            SAHARA_CLUSTER_NAME_MAX_LENGTH)

    def handle_create(self):
        plugin_name = self.properties[self.PLUGIN_NAME]
        hadoop_version = self.properties[self.HADOOP_VERSION]
        cluster_template_id = self.properties[self.CLUSTER_TEMPLATE_ID]
        image_id = self.properties[self.IMAGE_ID]
        # check that image is provided in case when
        # cluster template is missing one
        cluster_template = self.client().cluster_templates.get(
            cluster_template_id)
        if cluster_template.default_image_id is None and not image_id:
            msg = _("%(img)s must be provided: Referenced cluster template "
                    "%(tmpl)s has no default_image_id defined.") % {
                        'img': self.IMAGE_ID, 'tmpl': cluster_template_id}
            raise exception.StackValidationFailed(message=msg)

        key_name = self.properties[self.KEY_NAME]
        net_id = self.properties[self.MANAGEMENT_NETWORK]
        use_autoconfig = self.properties[self.USE_AUTOCONFIG]
        shares = self.properties[self.SHARES]

        cluster = self.client().clusters.create(
            self._cluster_name(),
            plugin_name, hadoop_version,
            cluster_template_id=cluster_template_id,
            user_keypair_id=key_name,
            default_image_id=image_id,
            net_id=net_id,
            use_autoconfig=use_autoconfig,
            shares=shares)
        LOG.info('Cluster "%s" is being started.', cluster.name)
        self.resource_id_set(cluster.id)
        return self.resource_id

    def check_create_complete(self, cluster_id):
        cluster = self.client().clusters.get(cluster_id)
        if cluster.status == self.CLUSTER_ERROR:
            raise exception.ResourceInError(resource_status=cluster.status)

        if cluster.status != self.CLUSTER_ACTIVE:
            return False

        LOG.info("Cluster '%s' has been created", cluster.name)
        return True

    def check_delete_complete(self, resource_id):
        if not resource_id:
            return True

        try:
            cluster = self.client().clusters.get(resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            LOG.info("Cluster '%s' has been deleted",
                     self._cluster_name())
            return True
        else:
            if cluster.status == self.CLUSTER_ERROR:
                raise exception.ResourceInError(resource_status=cluster.status)

        return False

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        cluster = self.client().clusters.get(self.resource_id)
        return getattr(cluster, name, None)

    def validate(self):
        res = super(SaharaCluster, self).validate()

        if res:
            return res

        self.client_plugin().validate_hadoop_version(
            self.properties[self.PLUGIN_NAME],
            self.properties[self.HADOOP_VERSION]
        )


def resource_mapping():
    return {
        'OS::Sahara::Cluster': SaharaCluster,
    }
