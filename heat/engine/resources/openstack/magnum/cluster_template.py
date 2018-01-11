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


class ClusterTemplate(resource.Resource):
    """A resource for the ClusterTemplate in Magnum.

    ClusterTemplate is an object that stores template information about the
    cluster which is used to create new clusters consistently.
    """

    support_status = support.SupportStatus(version='9.0.0')

    default_client_name = 'magnum'

    entity = 'cluster_templates'

    PROPERTIES = (
        NAME, IMAGE, FLAVOR, MASTER_FLAVOR, KEYPAIR,
        EXTERNAL_NETWORK, FIXED_NETWORK, FIXED_SUBNET, DNS_NAMESERVER,
        DOCKER_VOLUME_SIZE, DOCKER_STORAGE_DRIVER, COE,
        NETWORK_DRIVER, VOLUME_DRIVER, HTTP_PROXY, HTTPS_PROXY,
        NO_PROXY, LABELS, TLS_DISABLED, PUBLIC, REGISTRY_ENABLED,
        SERVER_TYPE, MASTER_LB_ENABLED, FLOATING_IP_ENABLED
    ) = (
        'name', 'image', 'flavor', 'master_flavor', 'keypair',
        'external_network', 'fixed_network', 'fixed_subnet', 'dns_nameserver',
        'docker_volume_size', 'docker_storage_driver', 'coe',
        'network_driver', 'volume_driver', 'http_proxy', 'https_proxy',
        'no_proxy', 'labels', 'tls_disabled', 'public', 'registry_enabled',
        'server_type', 'master_lb_enabled', 'floating_ip_enabled'
    )

    # Change it when magnum supports more function in the future.
    SUPPORTED_VOLUME_DRIVER = {'kubernetes': ['cinder'], 'swarm': ['rexray'],
                               'mesos': ['rexray']}

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The cluster template name.'),
        ),
        IMAGE: properties.Schema(
            properties.Schema.STRING,
            _('The image name or UUID to use as a base image for cluster.'),
            constraints=[
                constraints.CustomConstraint('glance.image')
            ],
            required=True
        ),
        FLAVOR: properties.Schema(
            properties.Schema.STRING,
            _('The nova flavor name or UUID to use when launching the '
              'cluster.'),
            constraints=[
                constraints.CustomConstraint('nova.flavor')
            ]
        ),
        MASTER_FLAVOR: properties.Schema(
            properties.Schema.STRING,
            _('The nova flavor name or UUID to use when launching the '
              'master node of the cluster.'),
            constraints=[
                constraints.CustomConstraint('nova.flavor')
            ]
        ),
        KEYPAIR: properties.Schema(
            properties.Schema.STRING,
            _('The name of the SSH keypair to load into the '
              'cluster nodes.'),
            constraints=[
                constraints.CustomConstraint('nova.keypair')
            ]
        ),
        EXTERNAL_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('The external neutron network name or UUID to attach the '
              'Cluster.'),
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ],
            required=True
        ),
        FIXED_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('The fixed neutron network name or UUID to attach the '
              'Cluster.'),
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ]
        ),
        FIXED_SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('The fixed neutron subnet name or UUID to attach the '
              'Cluster.'),
            constraints=[
                constraints.CustomConstraint('neutron.subnet')
            ]
        ),
        DNS_NAMESERVER: properties.Schema(
            properties.Schema.STRING,
            _('The DNS nameserver address.'),
            constraints=[
                constraints.CustomConstraint('ip_addr')
            ]
        ),
        DOCKER_VOLUME_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('The size in GB of the docker volume.'),
            constraints=[
                constraints.Range(min=1),
            ]
        ),
        DOCKER_STORAGE_DRIVER: properties.Schema(
            properties.Schema.STRING,
            _('Select a docker storage driver.'),
            constraints=[
                constraints.AllowedValues(['devicemapper', 'overlay'])
            ],
            default='devicemapper'
        ),
        COE: properties.Schema(
            properties.Schema.STRING,
            _('The Container Orchestration Engine for cluster.'),
            constraints=[
                constraints.AllowedValues(['kubernetes', 'swarm', 'mesos'])
            ],
            required=True
        ),
        NETWORK_DRIVER: properties.Schema(
            properties.Schema.STRING,
            _('The name of the driver used for instantiating '
              'container networks. By default, Magnum will choose the '
              'pre-configured network driver based on COE type.')
        ),
        VOLUME_DRIVER: properties.Schema(
            properties.Schema.STRING,
            _('The volume driver name for instantiating container volume.'),
            constraints=[
                constraints.AllowedValues(['cinder', 'rexray'])
            ]
        ),
        HTTP_PROXY: properties.Schema(
            properties.Schema.STRING,
            _('The http_proxy address to use for nodes in cluster.')
        ),
        HTTPS_PROXY: properties.Schema(
            properties.Schema.STRING,
            _('The https_proxy address to use for nodes in cluster.')
        ),
        NO_PROXY: properties.Schema(
            properties.Schema.STRING,
            _('A comma separated list of addresses for which proxies should '
              'not be used in the cluster.')
        ),
        LABELS: properties.Schema(
            properties.Schema.MAP,
            _('Arbitrary labels in the form of key=value pairs to '
              'associate with cluster.')
        ),
        TLS_DISABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Disable TLS in the cluster.'),
            default=False
        ),
        PUBLIC: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Make the cluster template public. To enable this option, you '
              'must own the right to publish in magnum. Which default set '
              'to admin only.'),
            update_allowed=True,
            default=False
        ),
        REGISTRY_ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Enable the docker registry in the cluster.'),
            default=False
        ),
        SERVER_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Specify the server type to be used.'),
            constraints=[
                constraints.AllowedValues(['vm', 'bm'])
            ],
            default='vm'
        ),
        MASTER_LB_ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Indicates whether created clusters should have a load '
              'balancer for master nodes or not.'),
            default=True
        ),
        FLOATING_IP_ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Indicates whether created clusters should have a floating '
              'ip or not.'),
            default=True
        ),
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.EXTERNAL_NETWORK],
                client_plugin=self.client_plugin('neutron'),
                finder='find_resourceid_by_name_or_id',
                entity='network'
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.FIXED_NETWORK],
                client_plugin=self.client_plugin('neutron'),
                finder='find_resourceid_by_name_or_id',
                entity='network'
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.FIXED_SUBNET],
                client_plugin=self.client_plugin('neutron'),
                finder='find_resourceid_by_name_or_id',
                entity='subnet'
            )
        ]

    def validate(self):
        """Validate the provided params."""
        super(ClusterTemplate, self).validate()

        coe = self.properties[self.COE]
        volume_driver = self.properties[self.VOLUME_DRIVER]

        # Confirm that volume driver is supported by Magnum COE per
        # SUPPORTED_VOLUME_DRIVER.
        value = self.SUPPORTED_VOLUME_DRIVER[coe]
        if volume_driver is not None and volume_driver not in value:
            msg = (_('Volume driver type %(driver)s is not supported by '
                     'COE:%(coe)s, expecting a %(supported_volume_driver)s '
                     'volume driver.') % {
                'driver': volume_driver, 'coe': coe,
                'supported_volume_driver': value})
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        args = {
            self.NAME: self.properties[
                self.NAME] or self.physical_resource_name()
        }
        for key in [self.IMAGE, self.FLAVOR, self.MASTER_FLAVOR, self.KEYPAIR,
                    self.EXTERNAL_NETWORK]:
            if self.properties[key] is not None:
                args["%s_id" % key] = self.properties[key]

        for p in [self.FIXED_NETWORK, self.FIXED_SUBNET,
                  self.DNS_NAMESERVER, self.DOCKER_VOLUME_SIZE,
                  self.DOCKER_STORAGE_DRIVER, self.COE, self.NETWORK_DRIVER,
                  self.VOLUME_DRIVER, self.HTTP_PROXY, self.HTTPS_PROXY,
                  self.NO_PROXY, self.LABELS, self.TLS_DISABLED, self.PUBLIC,
                  self.REGISTRY_ENABLED, self.SERVER_TYPE,
                  self.MASTER_LB_ENABLED, self.FLOATING_IP_ENABLED]:
            if self.properties[p] is not None:
                args[p] = self.properties[p]

        ct = self.client().cluster_templates.create(**args)
        self.resource_id_set(ct.uuid)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            patch = [{'op': 'replace', 'path': '/' + k, 'value': v}
                     for k, v in six.iteritems(prop_diff)]
            self.client().cluster_templates.update(self.resource_id, patch)
            return self.resource_id

    def check_update_complete(self, id):
        cluster_template = self.client().cluster_templates.get(id)
        if cluster_template.status == 'UPDATE_IN_PROGRESS':
            return False
        elif cluster_template.status == 'UPDATE_COMPLETE':
            return True
        elif cluster_template.status == 'UPDATE_FAILED':
            msg = (_("Failed to update Cluster Template "
                     "'%(name)s' - %(reason)s")
                   % {'name': self.name,
                      'reason': cluster_template.status_reason})
            raise exception.ResourceInError(
                status_reason=msg, resource_status=cluster_template.status)

        else:
            msg = (_("Unknown status updating Cluster Template "
                     "'%(name)s' - %(reason)s")
                   % {'name': self.name,
                      'reason': cluster_template.status_reason})
            raise exception.ResourceUnknownStatus(
                status_reason=msg, resource_status=cluster_template.status)


def resource_mapping():
    return {
        'OS::Magnum::ClusterTemplate': ClusterTemplate
    }
