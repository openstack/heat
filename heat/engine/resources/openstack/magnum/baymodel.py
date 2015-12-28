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

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class BayModel(resource.Resource):
    """A resource for the BayModel in Magnum.

    BayModel is an object that stores template information about the bay which
    is used to create new bays consistently.
    """

    support_status = support.SupportStatus(version='5.0.0')

    PROPERTIES = (
        NAME, IMAGE, FLAVOR, MASTER_FLAVOR, KEYPAIR,
        EXTERNAL_NETWORK, FIXED_NETWORK, DNS_NAMESERVER,
        DOCKER_VOLUME_SIZE, SSH_AUTHORIZED_KEY, COE, NETWORK_DRIVER,
        HTTP_PROXY, HTTPS_PROXY, NO_PROXY, LABELS, TLS_DISABLED
    ) = (
        'name', 'image', 'flavor', 'master_flavor', 'keypair',
        'external_network', 'fixed_network', 'dns_nameserver',
        'docker_volume_size', 'ssh_authorized_key', 'coe', 'network_driver',
        'http_proxy', 'https_proxy', 'no_proxy', 'labels', 'tls_disabled'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The bay model name.'),
        ),
        IMAGE: properties.Schema(
            properties.Schema.STRING,
            _('The image name or UUID to use as a base image for this '
              'baymodel.'),
            constraints=[
                constraints.CustomConstraint('glance.image')
            ],
            required=True
        ),
        FLAVOR: properties.Schema(
            properties.Schema.STRING,
            _('The flavor of this bay model.'),
            constraints=[
                constraints.CustomConstraint('nova.flavor')
            ]
        ),
        MASTER_FLAVOR: properties.Schema(
            properties.Schema.STRING,
            _('The flavor of the master node for this bay model.'),
            constraints=[
                constraints.CustomConstraint('nova.flavor')
            ]
        ),
        KEYPAIR: properties.Schema(
            properties.Schema.STRING,
            _('The name or id of the nova ssh keypair.'),
            constraints=[
                constraints.CustomConstraint('nova.keypair')
            ],
            required=True
        ),
        EXTERNAL_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('The external network to attach the Bay.'),
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ],
            required=True
        ),
        FIXED_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('The fixed network to attach the Bay.'),
            constraints=[
                constraints.CustomConstraint('neutron.network')
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
        SSH_AUTHORIZED_KEY: properties.Schema(
            properties.Schema.STRING,
            _('The SSH Authorized Key.'),
        ),
        COE: properties.Schema(
            properties.Schema.STRING,
            _('The Container Orchestration Engine for this bay model.'),
            constraints=[
                constraints.AllowedValues(['kubernetes', 'swarm'])
            ],
            required=True
        ),
        NETWORK_DRIVER: properties.Schema(
            properties.Schema.STRING,
            _('The name of the driver used for instantiating '
              'container networks. By default, Magnum will choose the '
              'pre-configured network driver based on COE type.'),
            support_status=support.SupportStatus(version='6.0.0')
        ),
        HTTP_PROXY: properties.Schema(
            properties.Schema.STRING,
            _('The http_proxy address to use for nodes in bay.'),
            support_status=support.SupportStatus(version='6.0.0')
        ),
        HTTPS_PROXY: properties.Schema(
            properties.Schema.STRING,
            _('The https_proxy address to use for nodes in bay.'),
            support_status=support.SupportStatus(version='6.0.0')
        ),
        NO_PROXY: properties.Schema(
            properties.Schema.STRING,
            _('A comma separated list of addresses for which proxies should '
              'not be used in the bay.'),
            support_status=support.SupportStatus(version='6.0.0')
        ),
        LABELS: properties.Schema(
            properties.Schema.MAP,
            _('Arbitrary labels in the form of key=value pairs to '
              'associate with a baymodel.'),
            support_status=support.SupportStatus(version='6.0.0')
        ),
        TLS_DISABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Disable TLS in the Bay.'),
            default=False,
            support_status=support.SupportStatus(version='6.0.0')
        ),

    }

    default_client_name = 'magnum'

    entity = 'baymodels'

    def handle_create(self):
        args = {
            'name': self.properties[self.NAME],
            'image_id': self.properties[self.IMAGE],
            'flavor_id': self.properties[self.FLAVOR],
            'master_flavor_id': self.properties[self.MASTER_FLAVOR],
            'keypair_id': self.properties[self.KEYPAIR],
            'external_network_id': self.properties[self.EXTERNAL_NETWORK],
            'fixed_network': self.properties[self.FIXED_NETWORK],
            'dns_nameserver': self.properties[self.DNS_NAMESERVER],
            'docker_volume_size': self.properties[self.DOCKER_VOLUME_SIZE],
            'ssh_authorized_key': self.properties[self.SSH_AUTHORIZED_KEY],
            'coe': self.properties[self.COE],
        }
        if self.properties[self.NETWORK_DRIVER]:
            args['network_driver'] = self.properties[self.NETWORK_DRIVER]
        if self.properties[self.HTTP_PROXY]:
            args['http_proxy'] = self.properties[self. HTTP_PROXY]
        if self.properties[self.HTTPS_PROXY]:
            args['https_proxy'] = self.properties[self.HTTPS_PROXY]
        if self.properties[self.NO_PROXY]:
            args['no_proxy'] = self.properties[self.NO_PROXY]
        if self.properties[self.LABELS]:
            args['labels'] = self.properties[self.LABELS]
        if self.properties[self.TLS_DISABLED]:
            args['tls_disabled'] = self.properties[self.TLS_DISABLED]

        bm = self.client().baymodels.create(**args)
        self.resource_id_set(bm.uuid)


def resource_mapping():
    return {
        'OS::Magnum::BayModel': BayModel
    }
