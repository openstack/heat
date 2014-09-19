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
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class SaharaCluster(resource.Resource):

    PROPERTIES = (
        NAME, PLUGIN_NAME, HADOOP_VERSION, CLUSTER_TEMPLATE_ID,
        KEY_NAME, IMAGE, MANAGEMENT_NETWORK,
    ) = (
        'name', 'plugin_name', 'hadoop_version', 'cluster_template_id',
        'key_name', 'image', 'neutron_management_network',
    )

    ATTRIBUTES = (
        STATUS, INFO,
    ) = (
        "status", "info",
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Hadoop cluster name.'),
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
        CLUSTER_TEMPLATE_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of the Cluster Template used for '
              'Node Groups and configurations.'),
            required=True,
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
    }

    attributes_schema = {
        STATUS: attributes.Schema(
            _("Cluster status."),
        ),
        INFO: attributes.Schema(
            _("Cluster information."),
        ),
    }

    default_client_name = 'sahara'

    def _cluster_name(self):
        name = self.properties.get(self.NAME)
        if name:
            return name
        return self.physical_resource_name()

    def handle_create(self):
        plugin_name = self.properties[self.PLUGIN_NAME]
        hadoop_version = self.properties[self.HADOOP_VERSION]
        cluster_template_id = self.properties[self.CLUSTER_TEMPLATE_ID]
        image_id = self.properties.get(self.IMAGE)
        if image_id:
            image_id = self.client_plugin('glance').get_image_id(image_id)

        # check that image is provided in case when
        # cluster template is missing one
        cluster_template = self.client().cluster_templates.get(
            cluster_template_id)
        if cluster_template.default_image_id is None and not image_id:
            msg = _("%(img)s must be provided: Referenced cluster template "
                    "%(tmpl)s has no default_image_id defined.") % {
                        'img': self.IMAGE, 'tmpl': cluster_template_id}
            raise exception.StackValidationFailed(message=msg)

        key_name = self.properties.get(self.KEY_NAME)
        net_id = self.properties.get(self.MANAGEMENT_NETWORK)
        if net_id:
            net_id = self.client_plugin('neutron').find_neutron_resource(
                self.properties, self.MANAGEMENT_NETWORK, 'network')

        cluster = self.client().clusters.create(
            self._cluster_name(),
            plugin_name, hadoop_version,
            cluster_template_id=cluster_template_id,
            user_keypair_id=key_name,
            default_image_id=image_id,
            net_id=net_id)
        LOG.info(_('Cluster "%s" is being started.') % cluster.name)
        self.resource_id_set(cluster.id)
        return self.resource_id

    def check_create_complete(self, cluster_id):
        cluster = self.client().clusters.get(cluster_id)
        if cluster.status == 'Error':
            raise resource.ResourceInError(resource_status=cluster.status)

        if cluster.status != 'Active':
            return False

        LOG.info(_("Cluster '%s' has been created") % cluster.name)
        return True

    def handle_delete(self):
        if not self.resource_id:
            return

        try:
            self.client().clusters.delete(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)

        LOG.info(_("Cluster '%s' has been deleted")
                 % self._cluster_name())

    def _resolve_attribute(self, name):
        cluster = self.client().clusters.get(self.resource_id)
        return getattr(cluster, name, None)

    def validate(self):
        res = super(SaharaCluster, self).validate()
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
        'OS::Sahara::Cluster': SaharaCluster,
    }
