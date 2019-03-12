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

import copy

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import uuidutils
import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine.clients import progress
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import port as neutron_port
from heat.engine.resources.openstack.neutron import subnet
from heat.engine.resources.openstack.nova import server_network_mixin
from heat.engine.resources import scheduler_hints as sh
from heat.engine.resources import server_base
from heat.engine import support
from heat.engine import translation
from heat.rpc import api as rpc_api

cfg.CONF.import_opt('default_software_config_transport', 'heat.common.config')
cfg.CONF.import_opt('default_user_data_format', 'heat.common.config')

LOG = logging.getLogger(__name__)

NOVA_MICROVERSIONS = (MICROVERSION_TAGS, MICROVERSION_STR_NETWORK,
                      MICROVERSION_NIC_TAGS) = ('2.26', '2.37', '2.42')


class Server(server_base.BaseServer, sh.SchedulerHintsMixin,
             server_network_mixin.ServerNetworkMixin):
    """A resource for managing Nova instances.

    A Server resource manages the running virtual machine instance within an
    OpenStack cloud.
    """

    PROPERTIES = (
        NAME, IMAGE, BLOCK_DEVICE_MAPPING, BLOCK_DEVICE_MAPPING_V2,
        FLAVOR, FLAVOR_UPDATE_POLICY, IMAGE_UPDATE_POLICY, KEY_NAME,
        ADMIN_USER, AVAILABILITY_ZONE, SECURITY_GROUPS, NETWORKS,
        SCHEDULER_HINTS, METADATA, USER_DATA_FORMAT, USER_DATA,
        RESERVATION_ID, CONFIG_DRIVE, DISK_CONFIG, PERSONALITY,
        ADMIN_PASS, SOFTWARE_CONFIG_TRANSPORT, USER_DATA_UPDATE_POLICY,
        TAGS, DEPLOYMENT_SWIFT_DATA
    ) = (
        'name', 'image', 'block_device_mapping', 'block_device_mapping_v2',
        'flavor', 'flavor_update_policy', 'image_update_policy', 'key_name',
        'admin_user', 'availability_zone', 'security_groups', 'networks',
        'scheduler_hints', 'metadata', 'user_data_format', 'user_data',
        'reservation_id', 'config_drive', 'diskConfig', 'personality',
        'admin_pass', 'software_config_transport', 'user_data_update_policy',
        'tags', 'deployment_swift_data'
    )

    _BLOCK_DEVICE_MAPPING_KEYS = (
        BLOCK_DEVICE_MAPPING_DEVICE_NAME, BLOCK_DEVICE_MAPPING_VOLUME_ID,
        BLOCK_DEVICE_MAPPING_SNAPSHOT_ID,
        BLOCK_DEVICE_MAPPING_VOLUME_SIZE,
        BLOCK_DEVICE_MAPPING_DELETE_ON_TERM,
    ) = (
        'device_name', 'volume_id',
        'snapshot_id',
        'volume_size',
        'delete_on_termination',
    )

    _BLOCK_DEVICE_MAPPING_V2_KEYS = (
        BLOCK_DEVICE_MAPPING_DEVICE_NAME,
        BLOCK_DEVICE_MAPPING_VOLUME_ID,
        BLOCK_DEVICE_MAPPING_IMAGE_ID,
        BLOCK_DEVICE_MAPPING_IMAGE,
        BLOCK_DEVICE_MAPPING_SNAPSHOT_ID,
        BLOCK_DEVICE_MAPPING_SWAP_SIZE,
        BLOCK_DEVICE_MAPPING_DEVICE_TYPE,
        BLOCK_DEVICE_MAPPING_DISK_BUS,
        BLOCK_DEVICE_MAPPING_BOOT_INDEX,
        BLOCK_DEVICE_MAPPING_VOLUME_SIZE,
        BLOCK_DEVICE_MAPPING_DELETE_ON_TERM,
        BLOCK_DEVICE_MAPPING_EPHEMERAL_SIZE,
        BLOCK_DEVICE_MAPPING_EPHEMERAL_FORMAT,
    ) = (
        'device_name',
        'volume_id',
        'image_id',
        'image',
        'snapshot_id',
        'swap_size',
        'device_type',
        'disk_bus',
        'boot_index',
        'volume_size',
        'delete_on_termination',
        'ephemeral_size',
        'ephemeral_format'
    )

    _NETWORK_KEYS = (
        NETWORK_UUID, NETWORK_ID, NETWORK_FIXED_IP, NETWORK_PORT,
        NETWORK_SUBNET, NETWORK_PORT_EXTRA, NETWORK_FLOATING_IP,
        ALLOCATE_NETWORK, NIC_TAG,
    ) = (
        'uuid', 'network', 'fixed_ip', 'port',
        'subnet', 'port_extra_properties', 'floating_ip',
        'allocate_network', 'tag',
    )

    _IFACE_MANAGED_KEYS = (NETWORK_PORT, NETWORK_ID,
                           NETWORK_FIXED_IP, NETWORK_SUBNET)

    _SOFTWARE_CONFIG_FORMATS = (
        HEAT_CFNTOOLS, RAW, SOFTWARE_CONFIG
    ) = (
        'HEAT_CFNTOOLS', 'RAW', 'SOFTWARE_CONFIG'
    )

    _SOFTWARE_CONFIG_TRANSPORTS = (
        POLL_SERVER_CFN, POLL_SERVER_HEAT, POLL_TEMP_URL, ZAQAR_MESSAGE
    ) = (
        'POLL_SERVER_CFN', 'POLL_SERVER_HEAT', 'POLL_TEMP_URL', 'ZAQAR_MESSAGE'
    )

    _ALLOCATE_TYPES = (
        NETWORK_NONE, NETWORK_AUTO,
    ) = (
        'none', 'auto',
    )

    _DEPLOYMENT_SWIFT_DATA_KEYS = (
        CONTAINER, OBJECT
    ) = (
        'container', 'object',
    )

    ATTRIBUTES = (
        NAME_ATTR, ADDRESSES, NETWORKS_ATTR, FIRST_ADDRESS,
        INSTANCE_NAME, ACCESSIPV4, ACCESSIPV6, CONSOLE_URLS, TAGS_ATTR,
        OS_COLLECT_CONFIG
    ) = (
        'name', 'addresses', 'networks', 'first_address',
        'instance_name', 'accessIPv4', 'accessIPv6', 'console_urls', 'tags',
        'os_collect_config'
    )

    # Image Statuses
    IMAGE_STATUSES = (IMAGE_ACTIVE, IMAGE_ERROR,
                      IMAGE_DELETED) = ('active', 'error', 'deleted')

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Server name.'),
            update_allowed=True
        ),
        IMAGE: properties.Schema(
            properties.Schema.STRING,
            _('The ID or name of the image to boot with.'),
            constraints=[
                constraints.CustomConstraint('glance.image')
            ],
            update_allowed=True
        ),
        BLOCK_DEVICE_MAPPING: properties.Schema(
            properties.Schema.LIST,
            _('Block device mappings for this server.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    BLOCK_DEVICE_MAPPING_DEVICE_NAME: properties.Schema(
                        properties.Schema.STRING,
                        _('A device name where the volume will be '
                          'attached in the system at /dev/device_name. '
                          'This value is typically vda.'),
                        required=True
                    ),
                    BLOCK_DEVICE_MAPPING_VOLUME_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('The ID of the volume to boot from. Only one '
                          'of volume_id or snapshot_id should be '
                          'provided.'),
                        constraints=[
                            constraints.CustomConstraint('cinder.volume')
                        ]
                    ),
                    BLOCK_DEVICE_MAPPING_SNAPSHOT_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('The ID of the snapshot to create a volume '
                          'from.'),
                        constraints=[
                            constraints.CustomConstraint('cinder.snapshot')
                        ]
                    ),
                    BLOCK_DEVICE_MAPPING_VOLUME_SIZE: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The size of the volume, in GB. It is safe to '
                          'leave this blank and have the Compute service '
                          'infer the size.')
                    ),
                    BLOCK_DEVICE_MAPPING_DELETE_ON_TERM: properties.Schema(
                        properties.Schema.BOOLEAN,
                        _('Indicate whether the volume should be deleted '
                          'when the server is terminated.')
                    ),
                },
            )
        ),
        BLOCK_DEVICE_MAPPING_V2: properties.Schema(
            properties.Schema.LIST,
            _('Block device mappings v2 for this server.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    BLOCK_DEVICE_MAPPING_DEVICE_NAME: properties.Schema(
                        properties.Schema.STRING,
                        _('A device name where the volume will be '
                          'attached in the system at /dev/device_name. '
                          'This value is typically vda.'),
                    ),
                    BLOCK_DEVICE_MAPPING_VOLUME_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('The volume_id can be boot or non-boot device '
                          'to the server.'),
                        constraints=[
                            constraints.CustomConstraint('cinder.volume')
                        ]
                    ),
                    BLOCK_DEVICE_MAPPING_IMAGE_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('The ID of the image to create a volume from.'),
                        support_status=support.SupportStatus(
                            status=support.HIDDEN,
                            version='9.0.0',
                            message=_('Use property %s.') %
                                    BLOCK_DEVICE_MAPPING_IMAGE,
                            previous_status=support.SupportStatus(
                                status=support.DEPRECATED,
                                version='7.0.0',
                                previous_status=support.SupportStatus(
                                    version='5.0.0')
                            )
                        ),
                        constraints=[
                            constraints.CustomConstraint('glance.image')
                        ],
                    ),
                    BLOCK_DEVICE_MAPPING_IMAGE: properties.Schema(
                        properties.Schema.STRING,
                        _('The ID or name of the image '
                          'to create a volume from.'),
                        support_status=support.SupportStatus(version='7.0.0'),
                        constraints=[
                            constraints.CustomConstraint('glance.image')
                        ],
                    ),
                    BLOCK_DEVICE_MAPPING_SNAPSHOT_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('The ID of the snapshot to create a volume '
                          'from.'),
                        constraints=[
                            constraints.CustomConstraint('cinder.snapshot')
                        ]
                    ),
                    BLOCK_DEVICE_MAPPING_SWAP_SIZE: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The size of the swap, in MB.')
                    ),
                    BLOCK_DEVICE_MAPPING_EPHEMERAL_SIZE: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The size of the local ephemeral block device, '
                          'in GB.'),
                        support_status=support.SupportStatus(version='8.0.0'),
                        constraints=[constraints.Range(min=1)]
                    ),
                    BLOCK_DEVICE_MAPPING_EPHEMERAL_FORMAT: properties.Schema(
                        properties.Schema.STRING,
                        _('The format of the local ephemeral block device. '
                          'If no format is specified, uses default value, '
                          'defined in nova configuration file.'),
                        constraints=[
                            constraints.AllowedValues(['ext2', 'ext3', 'ext4',
                                                       'xfs', 'ntfs'])
                        ],
                        support_status=support.SupportStatus(version='8.0.0')
                    ),
                    BLOCK_DEVICE_MAPPING_DEVICE_TYPE: properties.Schema(
                        properties.Schema.STRING,
                        _('Device type: at the moment we can make distinction '
                          'only between disk and cdrom.'),
                        constraints=[
                            constraints.AllowedValues(['cdrom', 'disk']),
                        ],
                    ),
                    BLOCK_DEVICE_MAPPING_DISK_BUS: properties.Schema(
                        properties.Schema.STRING,
                        _('Bus of the device: hypervisor driver chooses a '
                          'suitable default if omitted.'),
                        constraints=[
                            constraints.AllowedValues(['ide', 'lame_bus',
                                                       'scsi', 'usb',
                                                       'virtio']),
                        ],
                    ),
                    BLOCK_DEVICE_MAPPING_BOOT_INDEX: properties.Schema(
                        properties.Schema.INTEGER,
                        _('Integer used for ordering the boot disks. If '
                          'it is not specified, value "0" will be set '
                          'for bootable sources (volume, snapshot, image); '
                          'value "-1" will be set for non-bootable sources.'),
                    ),
                    BLOCK_DEVICE_MAPPING_VOLUME_SIZE: properties.Schema(
                        properties.Schema.INTEGER,
                        _('Size of the block device in GB. If it is omitted, '
                          'hypervisor driver calculates size.'),
                    ),
                    BLOCK_DEVICE_MAPPING_DELETE_ON_TERM: properties.Schema(
                        properties.Schema.BOOLEAN,
                        _('Indicate whether the volume should be deleted '
                          'when the server is terminated.')
                    ),
                },
            ),
            support_status=support.SupportStatus(version='2015.1')
        ),
        FLAVOR: properties.Schema(
            properties.Schema.STRING,
            _('The ID or name of the flavor to boot onto.'),
            required=True,
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('nova.flavor')
            ]
        ),
        FLAVOR_UPDATE_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('Policy on how to apply a flavor update; either by requesting '
              'a server resize or by replacing the entire server.'),
            default='RESIZE',
            constraints=[
                constraints.AllowedValues(['RESIZE', 'REPLACE']),
            ],
            update_allowed=True
        ),
        IMAGE_UPDATE_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('Policy on how to apply an image-id update; either by '
              'requesting a server rebuild or by replacing '
              'the entire server.'),
            default='REBUILD',
            constraints=[
                constraints.AllowedValues(['REBUILD', 'REPLACE',
                                           'REBUILD_PRESERVE_EPHEMERAL']),
            ],
            update_allowed=True
        ),
        KEY_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of keypair to inject into the server.'),
            constraints=[
                constraints.CustomConstraint('nova.keypair')
            ]
        ),
        ADMIN_USER: properties.Schema(
            properties.Schema.STRING,
            _('Name of the administrative user to use on the server.'),
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='5.0.0',
                message=_('The default cloud-init user set up for each image '
                          '(e.g. "ubuntu" for Ubuntu 12.04+, "fedora" for '
                          'Fedora 19+ and "cloud-user" for CentOS/RHEL 6.5).'),
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    version='2014.1',
                    previous_status=support.SupportStatus(version='2013.2')
                )
            )
        ),
        AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _('Name of the availability zone for server placement.')
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('List of security group names or IDs. Cannot be used if '
              'neutron ports are associated with this server; assign '
              'security groups to the ports instead.'),
            default=[]
        ),
        NETWORKS: properties.Schema(
            properties.Schema.LIST,
            _('An ordered list of nics to be added to this server, with '
              'information about connected networks, fixed ips, port etc.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    NETWORK_UUID: properties.Schema(
                        properties.Schema.STRING,
                        _('ID of network to create a port on.'),
                        support_status=support.SupportStatus(
                            status=support.HIDDEN,
                            version='5.0.0',
                            previous_status=support.SupportStatus(
                                status=support.DEPRECATED,
                                message=_('Use property %s.') % NETWORK_ID,
                                version='2014.1'
                            )
                        ),
                        constraints=[
                            constraints.CustomConstraint('neutron.network')
                        ]
                    ),
                    NETWORK_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('Name or ID of network to create a port on.'),
                        constraints=[
                            constraints.CustomConstraint('neutron.network')
                        ]
                    ),
                    ALLOCATE_NETWORK: properties.Schema(
                        properties.Schema.STRING,
                        _('The special string values of network, '
                          'auto: means either a network that is already '
                          'available to the project will be used, or if one '
                          'does not exist, will be automatically created for '
                          'the project; none: means no networking will be '
                          'allocated for the created server. Supported by '
                          'Nova API since version "2.37". This property can '
                          'not be used with other network keys.'),
                        support_status=support.SupportStatus(version='9.0.0'),
                        constraints=[
                            constraints.AllowedValues(
                                [NETWORK_NONE, NETWORK_AUTO])
                        ],
                        update_allowed=True,
                    ),
                    NETWORK_FIXED_IP: properties.Schema(
                        properties.Schema.STRING,
                        _('Fixed IP address to specify for the port '
                          'created on the requested network.'),
                        constraints=[
                            constraints.CustomConstraint('ip_addr')
                        ]
                    ),
                    NETWORK_PORT: properties.Schema(
                        properties.Schema.STRING,
                        _('ID of an existing port to associate with this '
                          'server.'),
                        constraints=[
                            constraints.CustomConstraint('neutron.port')
                        ]
                    ),
                    NETWORK_PORT_EXTRA: properties.Schema(
                        properties.Schema.MAP,
                        _('Dict, which has expand properties for port. '
                          'Used only if port property is not specified '
                          'for creating port.'),
                        schema=neutron_port.Port.extra_properties_schema,
                        support_status=support.SupportStatus(version='6.0.0')
                    ),
                    NETWORK_SUBNET: properties.Schema(
                        properties.Schema.STRING,
                        _('Subnet in which to allocate the IP address for '
                          'port. Used for creating port, based on derived '
                          'properties. If subnet is specified, network '
                          'property becomes optional.'),
                        support_status=support.SupportStatus(version='5.0.0')
                    ),
                    NETWORK_FLOATING_IP: properties.Schema(
                        properties.Schema.STRING,
                        _('ID of the floating IP to associate.'),
                        support_status=support.SupportStatus(version='6.0.0')
                    ),
                    NIC_TAG: properties.Schema(
                        properties.Schema.STRING,
                        _('Port tag. Heat ignores any update on this property '
                          'as nova does not support it.'),
                        support_status=support.SupportStatus(version='9.0.0')
                    )
                },
            ),
            update_allowed=True
        ),
        SCHEDULER_HINTS: properties.Schema(
            properties.Schema.MAP,
            _('Arbitrary key-value pairs specified by the client to help '
              'boot a server.')
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Arbitrary key/value metadata to store for this server. Both '
              'keys and values must be 255 characters or less. Non-string '
              'values will be serialized to JSON (and the serialized '
              'string must be 255 characters or less).'),
            update_allowed=True,
            default={}
        ),
        USER_DATA_FORMAT: properties.Schema(
            properties.Schema.STRING,
            _('How the user_data should be formatted for the server. For '
              'HEAT_CFNTOOLS, the user_data is bundled as part of the '
              'heat-cfntools cloud-init boot configuration data. For RAW '
              'the user_data is passed to Nova unmodified. '
              'For SOFTWARE_CONFIG user_data is bundled as part of the '
              'software config data, and metadata is derived from any '
              'associated SoftwareDeployment resources.'),
            default=cfg.CONF.default_user_data_format,
            constraints=[
                constraints.AllowedValues(_SOFTWARE_CONFIG_FORMATS),
            ]
        ),
        SOFTWARE_CONFIG_TRANSPORT: properties.Schema(
            properties.Schema.STRING,
            _('How the server should receive the metadata required for '
              'software configuration. POLL_SERVER_CFN will allow calls to '
              'the cfn API action DescribeStackResource authenticated with '
              'the provided keypair. POLL_SERVER_HEAT will allow calls to '
              'the Heat API resource-show using the provided keystone '
              'credentials. POLL_TEMP_URL will create and populate a '
              'Swift TempURL with metadata for polling. ZAQAR_MESSAGE will '
              'create a dedicated zaqar queue and post the metadata '
              'for polling.'),
            default=cfg.CONF.default_software_config_transport,
            update_allowed=True,
            constraints=[
                constraints.AllowedValues(_SOFTWARE_CONFIG_TRANSPORTS),
            ]
        ),
        USER_DATA_UPDATE_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('Policy on how to apply a user_data update; either by '
              'ignoring it or by replacing the entire server.'),
            default='REPLACE',
            constraints=[
                constraints.AllowedValues(['REPLACE', 'IGNORE']),
            ],
            support_status=support.SupportStatus(version='6.0.0'),
            update_allowed=True
        ),
        USER_DATA: properties.Schema(
            properties.Schema.STRING,
            _('User data script to be executed by cloud-init. Changes cause '
              'replacement of the resource by default, but can be ignored '
              'altogether by setting the `user_data_update_policy` property.'),
            default='',
            update_allowed=True
        ),
        RESERVATION_ID: properties.Schema(
            properties.Schema.STRING,
            _('A UUID for the set of servers being requested.')
        ),
        CONFIG_DRIVE: properties.Schema(
            properties.Schema.BOOLEAN,
            _('If True, enable config drive on the server.')
        ),
        DISK_CONFIG: properties.Schema(
            properties.Schema.STRING,
            _('Control how the disk is partitioned when the server is '
              'created.'),
            constraints=[
                constraints.AllowedValues(['AUTO', 'MANUAL']),
            ]
        ),
        PERSONALITY: properties.Schema(
            properties.Schema.MAP,
            _('A map of files to create/overwrite on the server upon boot. '
              'Keys are file names and values are the file contents.'),
            support_status=support.SupportStatus(
                status=support.DEPRECATED,
                version='12.0.0',
                message=_('This is not supported with nova api '
                          'microversion 2.57 and above. '
                          'OS::Nova::Server resource will not support '
                          'it in the future. Please use user_data or metadata '
                          'instead. However, you can set heat config option '
                          'max_nova_api_microversion < 2.57 to use '
                          'this property in the meantime.')
            ),
            default={}
        ),
        ADMIN_PASS: properties.Schema(
            properties.Schema.STRING,
            _('The administrator password for the server.'),
            update_allowed=True
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('Server tags. Supported since client version 2.26.'),
            support_status=support.SupportStatus(version='8.0.0'),
            schema=properties.Schema(properties.Schema.STRING),
            update_allowed=True
        ),
        DEPLOYMENT_SWIFT_DATA: properties.Schema(
            properties.Schema.MAP,
            _('Swift container and object to use for storing deployment data '
              'for the server resource. The parameter is a map value '
              'with the keys "container" and "object", and the values '
              'are the corresponding container and object names. The '
              'software_config_transport parameter must be set to '
              'POLL_TEMP_URL for swift to be used. If not specified, '
              'and software_config_transport is set to POLL_TEMP_URL, a '
              'container will be automatically created from the resource '
              'name, and the object name will be a generated uuid.'),
            support_status=support.SupportStatus(version='9.0.0'),
            default={},
            update_allowed=True,
            schema={
                CONTAINER: properties.Schema(
                    properties.Schema.STRING,
                    _('Name of the container.'),
                    constraints=[
                        constraints.Length(min=1)
                    ]
                ),
                OBJECT: properties.Schema(
                    properties.Schema.STRING,
                    _('Name of the object.'),
                    constraints=[
                        constraints.Length(min=1)
                    ]
                )
            }
        )
    }

    attributes_schema = {
        NAME_ATTR: attributes.Schema(
            _('Name of the server.'),
            type=attributes.Schema.STRING
        ),
        ADDRESSES: attributes.Schema(
            _('A dict of all network addresses with corresponding port_id and '
              'subnets. Each network will have two keys in dict, they are '
              'network name and network id. The port ID may be obtained '
              'through the following expression: ``{get_attr: [<server>, '
              'addresses, <network name_or_id>, 0, port]}``. The subnets may '
              'be obtained trough the following expression: ``{get_attr: '
              '[<server>, addresses, <network name_or_id>, 0, subnets]}``. '
              'The network may be obtained through the following expression: '
              '``{get_attr: [<server>, addresses, <network name_or_id>, 0, '
              'network]}``.'),
            type=attributes.Schema.MAP,
            support_status=support.SupportStatus(
                version='11.0.0',
                status=support.SUPPORTED,
                message=_('The attribute was extended to include subnets and '
                          'network with version 11.0.0.'),
                previous_status=support.SupportStatus(
                    status=support.SUPPORTED
                )
            )
        ),
        NETWORKS_ATTR: attributes.Schema(
            _('A dict of assigned network addresses of the form: '
              '{"public": [ip1, ip2...], "private": [ip3, ip4], '
              '"public_uuid": [ip1, ip2...], "private_uuid": [ip3, ip4]}. '
              'Each network will have two keys in dict, they are network '
              'name and network id.'),
            type=attributes.Schema.MAP
        ),
        FIRST_ADDRESS: attributes.Schema(
            _('Convenience attribute to fetch the first assigned network '
              'address, or an empty string if nothing has been assigned at '
              'this time. Result may not be predictable if the server has '
              'addresses from more than one network.'),
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='5.0.0',
                message=_('Use the networks attribute instead of '
                          'first_address. For example: "{get_attr: '
                          '[<server name>, networks, <network name>, 0]}"'),
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    version='2014.2',
                    previous_status=support.SupportStatus(version='2013.2')
                )
            )
        ),
        INSTANCE_NAME: attributes.Schema(
            _('AWS compatible instance name.'),
            type=attributes.Schema.STRING
        ),
        ACCESSIPV4: attributes.Schema(
            _('The manually assigned alternative public IPv4 address '
              'of the server.'),
            type=attributes.Schema.STRING
        ),
        ACCESSIPV6: attributes.Schema(
            _('The manually assigned alternative public IPv6 address '
              'of the server.'),
            type=attributes.Schema.STRING
        ),
        CONSOLE_URLS: attributes.Schema(
            _("URLs of server's consoles. "
              "To get a specific console type, the requested type "
              "can be specified as parameter to the get_attr function, "
              "e.g. get_attr: [ <server>, console_urls, novnc ]. "
              "Currently supported types are "
              "novnc, xvpvnc, spice-html5, rdp-html5, serial and webmks."),
            support_status=support.SupportStatus(version='2015.1'),
            type=attributes.Schema.MAP
        ),
        TAGS_ATTR: attributes.Schema(
            _('Tags from the server. Supported since client version 2.26.'),
            support_status=support.SupportStatus(version='8.0.0'),
            type=attributes.Schema.LIST
        ),
        OS_COLLECT_CONFIG: attributes.Schema(
            _('The os-collect-config configuration for the server\'s local '
              'agent to be configured to connect to Heat to retrieve '
              'deployment data.'),
            support_status=support.SupportStatus(version='9.0.0'),
            type=attributes.Schema.MAP,
            cache_mode=attributes.Schema.CACHE_NONE
        ),
    }

    default_client_name = 'nova'

    def translation_rules(self, props):
        neutron_client_plugin = self.client_plugin('neutron')
        glance_client_plugin = self.client_plugin('glance')
        rules = [
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                translation_path=[self.NETWORKS, self.NETWORK_ID],
                value_name=self.NETWORK_UUID),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.FLAVOR],
                client_plugin=self.client_plugin('nova'),
                finder='find_flavor_by_name_or_id'),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.IMAGE],
                client_plugin=glance_client_plugin,
                finder='find_image_by_name_or_id'),
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                translation_path=[self.BLOCK_DEVICE_MAPPING_V2,
                                  self.BLOCK_DEVICE_MAPPING_IMAGE],
                value_name=self.BLOCK_DEVICE_MAPPING_IMAGE_ID),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.BLOCK_DEVICE_MAPPING_V2,
                                  self.BLOCK_DEVICE_MAPPING_IMAGE],
                client_plugin=glance_client_plugin,
                finder='find_image_by_name_or_id'),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.NETWORKS, self.NETWORK_ID],
                client_plugin=neutron_client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=neutron_client_plugin.RES_TYPE_NETWORK),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.NETWORKS, self.NETWORK_SUBNET],
                client_plugin=neutron_client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=neutron_client_plugin.RES_TYPE_SUBNET),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.NETWORKS, self.NETWORK_PORT],
                client_plugin=neutron_client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=neutron_client_plugin.RES_TYPE_PORT)
        ]
        return rules

    def __init__(self, name, json_snippet, stack):
        super(Server, self).__init__(name, json_snippet, stack)
        if self.user_data_software_config():
            self._register_access_key()
        self.default_collectors = ['ec2']

    def _config_drive(self):
        # This method is overridden by the derived CloudServer resource
        return self.properties[self.CONFIG_DRIVE]

    def user_data_raw(self):
        return self.properties[self.USER_DATA_FORMAT] == self.RAW

    def user_data_software_config(self):
        return self.properties[
            self.USER_DATA_FORMAT] == self.SOFTWARE_CONFIG

    def get_software_config(self, ud_content):
        with self.rpc_client().ignore_error_by_name('NotFound'):
            sc = self.rpc_client().show_software_config(
                self.context, ud_content)
            return sc[rpc_api.SOFTWARE_CONFIG_CONFIG]
        return ud_content

    def handle_create(self):
        security_groups = self.properties[self.SECURITY_GROUPS]

        user_data_format = self.properties[self.USER_DATA_FORMAT]
        ud_content = self.properties[self.USER_DATA]
        if self.user_data_software_config() or self.user_data_raw():
            if uuidutils.is_uuid_like(ud_content):
                # attempt to load the userdata from software config
                ud_content = self.get_software_config(ud_content)

        metadata = self.metadata_get(True) or {}

        if self.user_data_software_config():
            self._create_transport_credentials(self.properties)
            self._populate_deployments_metadata(metadata, self.properties)

        userdata = self.client_plugin().build_userdata(
            metadata,
            ud_content,
            instance_user=None,
            user_data_format=user_data_format)

        availability_zone = self.properties[self.AVAILABILITY_ZONE]
        instance_meta = self.properties[self.METADATA]
        if instance_meta:
            instance_meta = self.client_plugin().meta_serialize(
                instance_meta)

        scheduler_hints = self._scheduler_hints(
            self.properties[self.SCHEDULER_HINTS])

        nics = self._build_nics(self.properties[self.NETWORKS],
                                security_groups=security_groups)
        block_device_mapping = self._build_block_device_mapping(
            self.properties[self.BLOCK_DEVICE_MAPPING])
        block_device_mapping_v2 = self._build_block_device_mapping_v2(
            self.properties[self.BLOCK_DEVICE_MAPPING_V2])
        reservation_id = self.properties[self.RESERVATION_ID]
        disk_config = self.properties[self.DISK_CONFIG]
        admin_pass = self.properties[self.ADMIN_PASS] or None
        personality_files = self.properties[self.PERSONALITY]
        key_name = self.properties[self.KEY_NAME]
        flavor = self.properties[self.FLAVOR]
        image = self.properties[self.IMAGE]

        server = None
        try:
            server = self.client().servers.create(
                name=self._server_name(),
                image=image,
                flavor=flavor,
                key_name=key_name,
                security_groups=security_groups,
                userdata=userdata,
                meta=instance_meta,
                scheduler_hints=scheduler_hints,
                nics=nics,
                availability_zone=availability_zone,
                block_device_mapping=block_device_mapping,
                block_device_mapping_v2=block_device_mapping_v2,
                reservation_id=reservation_id,
                config_drive=self._config_drive(),
                disk_config=disk_config,
                files=personality_files,
                admin_pass=admin_pass)
        finally:
            # Avoid a race condition where the thread could be canceled
            # before the ID is stored
            if server is not None:
                self.resource_id_set(server.id)

        return server.id

    def check_create_complete(self, server_id):
        check = self.client_plugin()._check_active(server_id)
        if check:
            if self.properties[self.TAGS]:
                self._update_server_tags(self.properties[self.TAGS])
            self.store_external_ports()
        return check

    def _update_server_tags(self, tags):
        server = self.client().servers.get(self.resource_id)
        self.client().servers.set_tags(server, tags)

    def handle_check(self):
        server = self.client().servers.get(self.resource_id)
        status = self.client_plugin().get_status(server)
        checks = [{'attr': 'status', 'expected': 'ACTIVE', 'current': status}]
        self._verify_check_conditions(checks)

    def get_live_resource_data(self):
        try:
            server = self.client().servers.get(self.resource_id)
            server_data = server.to_dict()
            active = self.client_plugin()._check_active(server)
            if not active:
                # There is no difference what error raised, because update
                # method of resource just silently log it as warning.
                raise exception.Error(_('Server %s is not '
                                        'in ACTIVE state') % self.name)
        except Exception as ex:
            if self.client_plugin().is_not_found(ex):
                raise exception.EntityNotFound(entity='Resource',
                                               name=self.name)
            raise

        if self.client_plugin().is_version_supported(MICROVERSION_TAGS):
            tag_server = self.client().servers.get(self.resource_id)
            server_data['tags'] = tag_server.tag_list()
        return server, server_data

    def parse_live_resource_data(self, resource_properties, resource_data):
        server, server_data = resource_data
        result = {
            # there's a risk that flavor id will be int type, so cast to str
            self.FLAVOR: six.text_type(server_data.get(self.FLAVOR)['id']),
            self.IMAGE: six.text_type(server_data.get(self.IMAGE)['id']),
            self.NAME: server_data.get(self.NAME),
            self.METADATA: server_data.get(self.METADATA),
            self.NETWORKS: self._get_live_networks(server, resource_properties)
        }
        if 'tags' in server_data:
            result.update({self.TAGS: server_data['tags']})
        return result

    def _get_live_networks(self, server, props):
        reality_nets = self._add_attrs_for_address(server,
                                                   extend_networks=False)
        reality_net_ids = {}
        client_plugin = self.client_plugin('neutron')
        for net_key in reality_nets:
            try:
                net_id = client_plugin.find_resourceid_by_name_or_id(
                    client_plugin.RES_TYPE_NETWORK,
                    net_key)
            except Exception as ex:
                if (client_plugin.is_not_found(ex) or
                        client_plugin.is_no_unique(ex)):
                    net_id = None
                else:
                    raise
            if net_id:
                reality_net_ids[net_id] = reality_nets.get(net_key)

        resource_nets = props.get(self.NETWORKS)

        result_nets = []
        for net in resource_nets or []:
            net_id = self._get_network_id(net)
            if reality_net_ids.get(net_id):
                for idx, address in enumerate(reality_net_ids.get(net_id)):
                    if address['addr'] == net[self.NETWORK_FIXED_IP]:
                        result_nets.append(net)
                        reality_net_ids.get(net_id).pop(idx)
                        break

        for key, value in six.iteritems(reality_nets):
            for address in reality_nets[key]:
                new_net = {self.NETWORK_ID: key,
                           self.NETWORK_FIXED_IP: address['addr']}
                if address['port'] not in [port['id']
                                           for port in self._data_get_ports()]:
                    new_net.update({self.NETWORK_PORT: address['port']})
                result_nets.append(new_net)
        return result_nets

    @classmethod
    def _build_block_device_mapping(cls, bdm):
        if not bdm:
            return None
        bdm_dict = {}
        for mapping in bdm:
            mapping_parts = []
            snapshot_id = mapping.get(cls.BLOCK_DEVICE_MAPPING_SNAPSHOT_ID)
            if snapshot_id:
                mapping_parts.append(snapshot_id)
                mapping_parts.append('snap')
            else:
                volume_id = mapping.get(cls.BLOCK_DEVICE_MAPPING_VOLUME_ID)
                mapping_parts.append(volume_id)
                mapping_parts.append('')

            volume_size = mapping.get(cls.BLOCK_DEVICE_MAPPING_VOLUME_SIZE)
            delete = mapping.get(cls.BLOCK_DEVICE_MAPPING_DELETE_ON_TERM)
            if volume_size:
                mapping_parts.append(str(volume_size))
            else:
                mapping_parts.append('')
            if delete:
                mapping_parts.append(str(delete))

            device_name = mapping.get(cls.BLOCK_DEVICE_MAPPING_DEVICE_NAME)
            bdm_dict[device_name] = ':'.join(mapping_parts)

        return bdm_dict

    @classmethod
    def _build_block_device_mapping_v2(cls, bdm_v2):
        if not bdm_v2:
            return None

        bdm_v2_list = []
        for mapping in bdm_v2:
            bmd_dict = None
            if mapping.get(cls.BLOCK_DEVICE_MAPPING_VOLUME_ID):
                bmd_dict = {
                    'uuid': mapping.get(cls.BLOCK_DEVICE_MAPPING_VOLUME_ID),
                    'source_type': 'volume',
                    'destination_type': 'volume',
                    'boot_index': 0,
                    'delete_on_termination': False,
                }
            elif mapping.get(cls.BLOCK_DEVICE_MAPPING_SNAPSHOT_ID):
                bmd_dict = {
                    'uuid': mapping.get(cls.BLOCK_DEVICE_MAPPING_SNAPSHOT_ID),
                    'source_type': 'snapshot',
                    'destination_type': 'volume',
                    'boot_index': 0,
                    'delete_on_termination': False,
                }
            elif mapping.get(cls.BLOCK_DEVICE_MAPPING_IMAGE):
                bmd_dict = {
                    'uuid': mapping.get(cls.BLOCK_DEVICE_MAPPING_IMAGE),
                    'source_type': 'image',
                    'destination_type': 'volume',
                    'boot_index': 0,
                    'delete_on_termination': False,
                }
            elif mapping.get(cls.BLOCK_DEVICE_MAPPING_SWAP_SIZE):
                bmd_dict = {
                    'source_type': 'blank',
                    'destination_type': 'local',
                    'boot_index': -1,
                    'delete_on_termination': True,
                    'guest_format': 'swap',
                    'volume_size': mapping.get(
                        cls.BLOCK_DEVICE_MAPPING_SWAP_SIZE),
                }
            elif (mapping.get(cls.BLOCK_DEVICE_MAPPING_EPHEMERAL_SIZE) or
                  mapping.get(cls.BLOCK_DEVICE_MAPPING_EPHEMERAL_FORMAT)):
                bmd_dict = {
                    'source_type': 'blank',
                    'destination_type': 'local',
                    'boot_index': -1,
                    'delete_on_termination': True
                }
                ephemeral_size = mapping.get(
                    cls.BLOCK_DEVICE_MAPPING_EPHEMERAL_SIZE)
                if ephemeral_size:
                    bmd_dict.update({'volume_size': ephemeral_size})
                ephemeral_format = mapping.get(
                    cls.BLOCK_DEVICE_MAPPING_EPHEMERAL_FORMAT)
                if ephemeral_format:
                    bmd_dict.update({'guest_format': ephemeral_format})

            # NOTE(prazumovsky): In case of server doesn't take empty value of
            # device name, need to escape from such situation.
            device_name = mapping.get(cls.BLOCK_DEVICE_MAPPING_DEVICE_NAME)
            if device_name:
                bmd_dict[cls.BLOCK_DEVICE_MAPPING_DEVICE_NAME] = device_name

            update_props = (cls.BLOCK_DEVICE_MAPPING_DEVICE_TYPE,
                            cls.BLOCK_DEVICE_MAPPING_DISK_BUS,
                            cls.BLOCK_DEVICE_MAPPING_BOOT_INDEX,
                            cls.BLOCK_DEVICE_MAPPING_VOLUME_SIZE,
                            cls.BLOCK_DEVICE_MAPPING_DELETE_ON_TERM)

            for update_prop in update_props:
                if mapping.get(update_prop) is not None:
                    bmd_dict[update_prop] = mapping.get(update_prop)

            if bmd_dict:
                bdm_v2_list.append(bmd_dict)

        return bdm_v2_list

    def _get_subnets_attr(self, fixed_ips):
        subnets = []
        try:
            for fixed_ip in fixed_ips:
                if fixed_ip.get('subnet_id'):
                    subnets.append(self.client('neutron').show_subnet(
                        fixed_ip['subnet_id'])['subnet'])
        except Exception as ex:
            LOG.warning("Failed to fetch resource attributes: %s", ex)
            return
        return subnets

    def _get_network_attr(self, network_id):
        try:
            return self.client('neutron').show_network(network_id)['network']
        except Exception as ex:
            LOG.warning("Failed to fetch resource attributes: %s", ex)
            return

    def _add_attrs_for_address(self, server, extend_networks=True):
        """Adds port id, subnets and network attributes to addresses list.

        This method is used only for resolving attributes.
        :param server: The server resource
        :param extend_networks: When False the network is not extended, i.e
                                the net is returned without replacing name on
                                id.
        """
        nets = copy.deepcopy(server.addresses) or {}
        ifaces = server.interface_list()
        ip_mac_mapping_on_port_id = dict(((iface.fixed_ips[0]['ip_address'],
                                           iface.mac_addr), iface.port_id)
                                         for iface in ifaces)
        for net_name in nets:
            for addr in nets[net_name]:
                addr['port'] = ip_mac_mapping_on_port_id.get(
                    (addr['addr'], addr['OS-EXT-IPS-MAC:mac_addr']))
                # _get_live_networks() uses this method to get reality_nets.
                # We don't need to get subnets and network in that case. Only
                # do the external calls if extend_networks is true, i.e called
                # from _resolve_attribute()
                if not extend_networks:
                    continue
                try:
                    port = self.client('neutron').show_port(
                        addr['port'])['port']
                except Exception as ex:
                    addr['subnets'], addr['network'] = None, None
                    LOG.warning("Failed to fetch resource attributes: %s", ex)
                    continue
                addr['subnets'] = self._get_subnets_attr(port['fixed_ips'])
                addr['network'] = self._get_network_attr(port['network_id'])

        if extend_networks:
            return self._extend_networks(nets)
        else:
            return nets

    def _extend_networks(self, networks):
        """Method adds same networks with replaced name on network id.

        This method is used only for resolving attributes.
        """
        nets = copy.deepcopy(networks)
        client_plugin = self.client_plugin('neutron')
        for key in list(nets.keys()):
            try:
                net_id = client_plugin.find_resourceid_by_name_or_id(
                    client_plugin.RES_TYPE_NETWORK,
                    key)
            except Exception as ex:
                if (client_plugin.is_not_found(ex) or
                        client_plugin.is_no_unique(ex)):
                    net_id = None
                else:
                    raise
            if net_id:
                nets[net_id] = nets[key]
        return nets

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        if name == self.FIRST_ADDRESS:
            return self.client_plugin().server_to_ipaddress(
                self.resource_id) or ''
        if name == self.OS_COLLECT_CONFIG:
            return self.metadata_get().get('os-collect-config', {})
        if name == self.NAME_ATTR:
            return self._server_name()
        try:
            server = self.client().servers.get(self.resource_id)
        except Exception as e:
            self.client_plugin().ignore_not_found(e)
            return ''
        if name == self.ADDRESSES:
            return self._add_attrs_for_address(server)
        if name == self.NETWORKS_ATTR:
            return self._extend_networks(server.networks)
        if name == self.INSTANCE_NAME:
            return getattr(server, 'OS-EXT-SRV-ATTR:instance_name', None)
        if name == self.ACCESSIPV4:
            return server.accessIPv4
        if name == self.ACCESSIPV6:
            return server.accessIPv6
        if name == self.CONSOLE_URLS:
            return self.client_plugin('nova').get_console_urls(server)
        if name == self.TAGS_ATTR:
            if self.client_plugin().is_version_supported(MICROVERSION_TAGS):
                return self.client().servers.tag_list(server)
            return None

    def add_dependencies(self, deps):
        super(Server, self).add_dependencies(deps)
        # Depend on any Subnet in this template with the same
        # network_id as the networks attached to this server.
        # It is not known which subnet a server might be assigned
        # to so all subnets in a network should be created before
        # the servers in that network.
        try:
            nets = self.properties[self.NETWORKS]
        except (ValueError, TypeError):
            # Properties errors will be caught later in validation,
            # where we can report them in their proper context.
            return
        if not nets:
            return
        for res in six.itervalues(self.stack):
            if res.has_interface('OS::Neutron::Subnet'):
                try:
                    subnet_net = res.properties.get(subnet.Subnet.NETWORK)
                except (ValueError, TypeError):
                    # Properties errors will be caught later in validation,
                    # where we can report them in their proper context.
                    continue
                # Be wary of the case where we do not know a subnet's
                # network. If that's the case, be safe and add it as a
                # dependency.
                if not subnet_net:
                    deps += (self, res)
                    continue
                for net in nets:
                    # worry about network_id because that could be the match
                    # assigned to the subnet as well and could have been
                    # created by this stack. Regardless, the server should
                    # still wait on the subnet.
                    net_id = net.get(self.NETWORK_ID)
                    if net_id and net_id == subnet_net:
                        deps += (self, res)
                        break
                    # If we don't know a given net_id right now, it's
                    # plausible this subnet depends on it.
                    if not net_id:
                        deps += (self, res)
                        break

    def _update_flavor(self, after_props):
        flavor = after_props[self.FLAVOR]
        handler_args = checker_args = {'args': (flavor,)}
        prg_resize = progress.ServerUpdateProgress(self.resource_id,
                                                   'resize',
                                                   handler_extra=handler_args,
                                                   checker_extra=checker_args)
        prg_verify = progress.ServerUpdateProgress(self.resource_id,
                                                   'verify_resize')
        return prg_resize, prg_verify

    def _update_image(self, after_props):
        image_update_policy = after_props[self.IMAGE_UPDATE_POLICY]

        instance_meta = after_props[self.METADATA]
        if instance_meta is not None:
            instance_meta = self.client_plugin().meta_serialize(
                instance_meta)
        personality_files = after_props[self.PERSONALITY]

        image = after_props[self.IMAGE]
        preserve_ephemeral = (
            image_update_policy == 'REBUILD_PRESERVE_EPHEMERAL')
        password = after_props[self.ADMIN_PASS]
        kwargs = {'password': password,
                  'preserve_ephemeral': preserve_ephemeral,
                  'meta': instance_meta,
                  'files': personality_files}
        prg = progress.ServerUpdateProgress(self.resource_id,
                                            'rebuild',
                                            handler_extra={'args': (image,),
                                                           'kwargs': kwargs})
        return prg

    def _update_networks(self, server, after_props):
        updaters = []
        new_networks = after_props[self.NETWORKS]
        old_networks = self.properties[self.NETWORKS]
        security_groups = after_props[self.SECURITY_GROUPS]

        if not server:
            server = self.client().servers.get(self.resource_id)
        interfaces = server.interface_list()
        remove_ports, add_nets = self.calculate_networks(
            old_networks, new_networks, interfaces, security_groups)

        for port in remove_ports:
            updaters.append(
                progress.ServerUpdateProgress(
                    self.resource_id, 'interface_detach',
                    handler_extra={'args': (port,)},
                    checker_extra={'args': (port,)})
            )

        for args in add_nets:
            updaters.append(
                progress.ServerUpdateProgress(
                    self.resource_id, 'interface_attach',
                    handler_extra={'kwargs': args},
                    checker_extra={'args': (args['port_id'],)})
            )

        return updaters

    def needs_replace_with_prop_diff(self, changed_properties_set,
                                     after_props, before_props):
        """Needs replace based on prop_diff."""
        if self.FLAVOR in changed_properties_set:
            flavor_update_policy = (
                after_props.get(self.FLAVOR_UPDATE_POLICY) or
                before_props.get(self.FLAVOR_UPDATE_POLICY))
            if flavor_update_policy == 'REPLACE':
                return True

        if self.IMAGE in changed_properties_set:
            image_update_policy = (
                after_props.get(self.IMAGE_UPDATE_POLICY) or
                before_props.get(self.IMAGE_UPDATE_POLICY))
            if image_update_policy == 'REPLACE':
                return True

        if self.USER_DATA in changed_properties_set:
            ud_update_policy = (
                after_props.get(self.USER_DATA_UPDATE_POLICY) or
                before_props.get(self.USER_DATA_UPDATE_POLICY))
            return ud_update_policy == 'REPLACE'

    def needs_replace_failed(self):
        if not self.resource_id:
            return True

        with self.client_plugin().ignore_not_found:
            server = self.client().servers.get(self.resource_id)
            return server.status in ('ERROR', 'DELETED', 'SOFT_DELETED')

        return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        updaters = super(Server, self).handle_update(
            json_snippet,
            tmpl_diff,
            prop_diff)
        server = None

        after_props = json_snippet.properties(self.properties_schema,
                                              self.context)
        if self.METADATA in prop_diff:
            server = self.client_plugin().get_server(self.resource_id)
            self.client_plugin().meta_update(server,
                                             after_props[self.METADATA])

        if self.TAGS in prop_diff:
            self._update_server_tags(after_props[self.TAGS] or [])

        if self.NAME in prop_diff:
            if not server:
                server = self.client_plugin().get_server(self.resource_id)
            self.client_plugin().rename(server, after_props[self.NAME])

        if self.NETWORKS in prop_diff:
            updaters.extend(self._update_networks(server, after_props))

        if self.FLAVOR in prop_diff:
            updaters.extend(self._update_flavor(after_props))

        if self.IMAGE in prop_diff:
            updaters.append(self._update_image(after_props))
        elif self.ADMIN_PASS in prop_diff:
            if not server:
                server = self.client_plugin().get_server(self.resource_id)
            server.change_password(after_props[self.ADMIN_PASS])

        # NOTE(pas-ha) optimization is possible (starting first task
        # right away), but we'd rather not, as this method already might
        # have called several APIs
        return updaters

    def check_update_complete(self, updaters):
        """Push all updaters to completion in list order."""
        for prg in updaters:
            if not prg.called:
                handler = getattr(self.client_plugin(), prg.handler)
                prg.called = handler(*prg.handler_args,
                                     **prg.handler_kwargs)
                return False
            if not prg.complete:
                check_complete = getattr(self.client_plugin(), prg.checker)
                prg.complete = check_complete(*prg.checker_args,
                                              **prg.checker_kwargs)
                break
        status = all(prg.complete for prg in updaters)
        if status:
            self.store_external_ports()
        return status

    def _validate_block_device_mapping(self):

        # either volume_id or snapshot_id needs to be specified, but not both
        # for block device mapping.
        bdm = self.properties[self.BLOCK_DEVICE_MAPPING] or []
        bdm_v2 = self.properties[self.BLOCK_DEVICE_MAPPING_V2] or []
        image = self.properties[self.IMAGE]
        if bdm and bdm_v2:
            raise exception.ResourcePropertyConflict(
                self.BLOCK_DEVICE_MAPPING, self.BLOCK_DEVICE_MAPPING_V2)
        bootable = image is not None
        for mapping in bdm:
            device_name = mapping[self.BLOCK_DEVICE_MAPPING_DEVICE_NAME]
            if device_name == 'vda':
                bootable = True

            volume_id = mapping.get(self.BLOCK_DEVICE_MAPPING_VOLUME_ID)
            snapshot_id = mapping.get(self.BLOCK_DEVICE_MAPPING_SNAPSHOT_ID)
            if volume_id is not None and snapshot_id is not None:
                raise exception.ResourcePropertyConflict(
                    self.BLOCK_DEVICE_MAPPING_VOLUME_ID,
                    self.BLOCK_DEVICE_MAPPING_SNAPSHOT_ID)
            if volume_id is None and snapshot_id is None:
                msg = _('Either volume_id or snapshot_id must be specified for'
                        ' device mapping %s') % device_name
                raise exception.StackValidationFailed(message=msg)

        bootable_devs = [image]
        for mapping in bdm_v2:
            volume_id = mapping.get(self.BLOCK_DEVICE_MAPPING_VOLUME_ID)
            snapshot_id = mapping.get(self.BLOCK_DEVICE_MAPPING_SNAPSHOT_ID)
            image_id = mapping.get(self.BLOCK_DEVICE_MAPPING_IMAGE)
            boot_index = mapping.get(self.BLOCK_DEVICE_MAPPING_BOOT_INDEX)
            swap_size = mapping.get(self.BLOCK_DEVICE_MAPPING_SWAP_SIZE)
            ephemeral = (mapping.get(
                self.BLOCK_DEVICE_MAPPING_EPHEMERAL_SIZE) or mapping.get(
                self.BLOCK_DEVICE_MAPPING_EPHEMERAL_FORMAT))

            property_tuple = (volume_id, snapshot_id, image_id, swap_size,
                              ephemeral)

            if property_tuple.count(None) < 4:
                raise exception.ResourcePropertyConflict(
                    self.BLOCK_DEVICE_MAPPING_VOLUME_ID,
                    self.BLOCK_DEVICE_MAPPING_SNAPSHOT_ID,
                    self.BLOCK_DEVICE_MAPPING_IMAGE,
                    self.BLOCK_DEVICE_MAPPING_SWAP_SIZE,
                    self.BLOCK_DEVICE_MAPPING_EPHEMERAL_SIZE,
                    self.BLOCK_DEVICE_MAPPING_EPHEMERAL_FORMAT
                )

            if property_tuple.count(None) == 5:
                msg = _('Either volume_id, snapshot_id, image_id, swap_size, '
                        'ephemeral_size or ephemeral_format must be '
                        'specified.')
                raise exception.StackValidationFailed(message=msg)

            if any((volume_id is not None, snapshot_id is not None,
                    image_id is not None)):
                # boot_index is not specified, set boot_index=0 when
                # build_block_device_mapping for volume, snapshot, image
                if boot_index is None or boot_index == 0:
                    bootable = True
                    bootable_devs.append(volume_id)
                    bootable_devs.append(snapshot_id)
                    bootable_devs.append(image_id)
        if not bootable:
            msg = _('Neither image nor bootable volume is specified for '
                    'instance %s') % self.name
            raise exception.StackValidationFailed(message=msg)
        if bdm_v2 and len(list(
                dev for dev in bootable_devs if dev is not None)) != 1:
            msg = _('Multiple bootable sources for instance %s.') % self.name
            raise exception.StackValidationFailed(message=msg)

    def _validate_image_flavor(self, image, flavor):
        try:
            image_obj = self.client_plugin('glance').get_image(image)
            flavor_obj = self.client_plugin().get_flavor(flavor)
        except Exception as ex:
            # Flavor or image may not have been created in the backend
            # yet when they are part of the same stack/template.
            if (self.client_plugin().is_not_found(ex) or
                    self.client_plugin('glance').is_not_found(ex)):
                return
            raise
        else:
            if image_obj.status.lower() != self.IMAGE_ACTIVE:
                msg = _('Image status is required to be %(cstatus)s not '
                        '%(wstatus)s.') % {
                    'cstatus': self.IMAGE_ACTIVE,
                    'wstatus': image_obj.status}
                raise exception.StackValidationFailed(message=msg)

            # validate image/flavor combination
            if flavor_obj.ram < image_obj.min_ram:
                msg = _('Image %(image)s requires %(imram)s minimum ram. '
                        'Flavor %(flavor)s has only %(flram)s.') % {
                    'image': image, 'imram': image_obj.min_ram,
                    'flavor': flavor, 'flram': flavor_obj.ram}
                raise exception.StackValidationFailed(message=msg)

            # validate image/flavor disk compatibility
            if flavor_obj.disk < image_obj.min_disk:
                msg = _('Image %(image)s requires %(imsz)s GB minimum '
                        'disk space. Flavor %(flavor)s has only '
                        '%(flsz)s GB.') % {
                    'image': image, 'imsz': image_obj.min_disk,
                    'flavor': flavor, 'flsz': flavor_obj.disk}
                raise exception.StackValidationFailed(message=msg)

    def validate(self):
        """Validate any of the provided params."""
        super(Server, self).validate()

        if self.user_data_software_config():
            if 'deployments' in self.t.metadata():
                msg = _('deployments key not allowed in resource metadata '
                        'with user_data_format of SOFTWARE_CONFIG')
                raise exception.StackValidationFailed(message=msg)

        self._validate_block_device_mapping()

        # make sure the image exists if specified.
        image = self.properties[self.IMAGE]
        flavor = self.properties[self.FLAVOR]
        if image:
            self._validate_image_flavor(image, flavor)

        networks = self.properties[self.NETWORKS] or []
        for network in networks:
            self._validate_network(network)

        has_str_net = self._str_network(networks) is not None
        if has_str_net:
            if len(networks) != 1:
                msg = _('Property "%s" can not be specified if '
                        'multiple network interfaces set for '
                        'server.') % self.ALLOCATE_NETWORK
                raise exception.StackValidationFailed(message=msg)
            # Check if str_network is allowed to use
            if not self.client_plugin().is_version_supported(
                    MICROVERSION_STR_NETWORK):
                msg = (_('Cannot use "%s" property - compute service '
                         'does not support the required api '
                         'microversion.') % self.ALLOCATE_NETWORK)
                raise exception.StackValidationFailed(message=msg)

        # record if any networks include explicit ports
        has_port = any(n[self.NETWORK_PORT] is not None for n in networks)
        # if 'security_groups' present for the server and explicit 'port'
        # in one or more entries in 'networks', raise validation error
        if has_port and self.properties[self.SECURITY_GROUPS]:
            raise exception.ResourcePropertyConflict(
                self.SECURITY_GROUPS,
                "/".join([self.NETWORKS, self.NETWORK_PORT]))

        # Check if nic tag is allowed to use
        if self._is_nic_tagged(networks=networks):
            if not self.client_plugin().is_version_supported(
                    MICROVERSION_NIC_TAGS):
                msg = (_('Cannot use "%s" property in networks - '
                         'nova does not support required '
                         'api microversion.'), self.NIC_TAG)
                raise exception.StackValidationFailed(message=msg)

        # Check if tags is allowed to use
        if self.properties[self.TAGS]:
            if not self.client_plugin().is_version_supported(
                    MICROVERSION_TAGS):
                msg = (_('Cannot use "%s" property - nova does not support '
                         'required api microversion.') % self.TAGS)
                raise exception.StackValidationFailed(message=msg)

        # retrieve provider's absolute limits if it will be needed
        metadata = self.properties[self.METADATA]
        personality = self.properties[self.PERSONALITY]
        if metadata or personality:
            limits = self.client_plugin().absolute_limits()

        # verify that the number of metadata entries is not greater
        # than the maximum number allowed in the provider's absolute
        # limits
        if metadata:
            msg = _('Instance metadata must not contain greater than %s '
                    'entries.  This is the maximum number allowed by your '
                    'service provider') % limits['maxServerMeta']
            self._check_maximum(len(metadata),
                                limits['maxServerMeta'], msg)

        # verify the number of personality files and the size of each
        # personality file against the provider's absolute limits
        if personality:
            msg = _("The personality property may not contain "
                    "greater than %s entries.") % limits['maxPersonality']
            self._check_maximum(len(personality),
                                limits['maxPersonality'], msg)

            for path, contents in personality.items():
                msg = (_("The contents of personality file \"%(path)s\" "
                         "is larger than the maximum allowed personality "
                         "file size (%(max_size)s bytes).") %
                       {'path': path,
                        'max_size': limits['maxPersonalitySize']})
                self._check_maximum(len(bytes(contents.encode('utf-8'))
                                        ) if contents is not None else 0,
                                    limits['maxPersonalitySize'], msg)

    def _delete(self):
        if self.user_data_software_config():
            self._delete_queue()
            self._delete_user()
            self._delete_temp_url()

        # remove internal and external ports
        self._delete_internal_ports()
        self.data_delete('external_ports')

        if self.resource_id is None:
            return

        try:
            self.client().servers.delete(self.resource_id)
        except Exception as e:
            self.client_plugin().ignore_not_found(e)
            return
        return progress.ServerDeleteProgress(self.resource_id)

    def handle_snapshot_delete(self, state):

        if state[1] != self.FAILED and self.resource_id:
            image_id = self.client().servers.create_image(
                self.resource_id, self.physical_resource_name())
            return progress.ServerDeleteProgress(
                self.resource_id, image_id, False)
        return self._delete()

    def handle_delete(self):

        return self._delete()

    def check_delete_complete(self, prg):
        if not prg:
            return True
        if not prg.image_complete:
            image = self.client_plugin('glance').get_image(prg.image_id)
            if image.status.lower() in (self.IMAGE_ERROR,
                                        self.IMAGE_DELETED):
                raise exception.Error(image.status)
            elif image.status.lower() == self.IMAGE_ACTIVE:
                prg.image_complete = True
                if not self._delete():
                    return True
            return False

        return self.client_plugin().check_delete_server_complete(
            prg.server_id)

    def handle_suspend(self):
        """Suspend a server.

        Note we do not wait for the SUSPENDED state, this is polled for by
        check_suspend_complete in a similar way to the create logic so we can
        take advantage of coroutines.
        """
        if self.resource_id is None:
            raise exception.Error(_('Cannot suspend %s, resource_id not set') %
                                  self.name)

        try:
            server = self.client().servers.get(self.resource_id)
        except Exception as e:
            if self.client_plugin().is_not_found(e):
                raise exception.NotFound(_('Failed to find server %s') %
                                         self.resource_id)
            else:
                raise
        else:
            # if the server has been suspended successful,
            # no need to suspend again
            if self.client_plugin().get_status(server) != 'SUSPENDED':
                LOG.debug('suspending server %s', self.resource_id)
                server.suspend()
            return server.id

    def check_suspend_complete(self, server_id):
        cp = self.client_plugin()
        server = cp.fetch_server(server_id)
        if not server:
            return False
        status = cp.get_status(server)
        LOG.debug('%(name)s check_suspend_complete status = %(status)s',
                  {'name': self.name, 'status': status})
        if status in list(cp.deferred_server_statuses + ['ACTIVE']):
            return status == 'SUSPENDED'
        else:
            exc = exception.ResourceUnknownStatus(
                result=_('Suspend of server %s failed') % server.name,
                resource_status=status)
            raise exc

    def handle_resume(self):
        """Resume a server.

        Note we do not wait for the ACTIVE state, this is polled for by
        check_resume_complete in a similar way to the create logic so we can
        take advantage of coroutines.
        """
        if self.resource_id is None:
            raise exception.Error(_('Cannot resume %s, resource_id not set') %
                                  self.name)

        try:
            server = self.client().servers.get(self.resource_id)
        except Exception as e:
            if self.client_plugin().is_not_found(e):
                raise exception.NotFound(_('Failed to find server %s') %
                                         self.resource_id)
            else:
                raise
        else:
            # if the server has been resumed successful,
            # no need to resume again
            if self.client_plugin().get_status(server) != 'ACTIVE':
                LOG.debug('resuming server %s', self.resource_id)
                server.resume()
            return server.id

    def check_resume_complete(self, server_id):
        return self.client_plugin()._check_active(server_id)

    def handle_snapshot(self):
        image_id = self.client().servers.create_image(
            self.resource_id, self.physical_resource_name())
        self.data_set('snapshot_image_id', image_id)
        return image_id

    def check_snapshot_complete(self, image_id):
        image = self.client_plugin('glance').get_image(image_id)
        if image.status.lower() == self.IMAGE_ACTIVE:
            return True
        elif image.status.lower() in (self.IMAGE_ERROR, self.IMAGE_DELETED):
            raise exception.Error(image.status)

        return False

    def handle_delete_snapshot(self, snapshot):
        image_id = snapshot['resource_data'].get('snapshot_image_id')
        with self.client_plugin('glance').ignore_not_found:
            self.client('glance').images.delete(image_id)

    def handle_restore(self, defn, restore_data):
        image_id = restore_data['resource_data']['snapshot_image_id']
        props = dict((k, v) for k, v in self.properties.data.items()
                     if v is not None)
        for key in [self.BLOCK_DEVICE_MAPPING, self.BLOCK_DEVICE_MAPPING_V2,
                    self.NETWORKS]:
            if props.get(key) is not None:
                props[key] = list(dict((k, v) for k, v in prop.items()
                                       if v is not None)
                                  for prop in props[key])
        props[self.IMAGE] = image_id
        return defn.freeze(properties=props)

    def prepare_for_replace(self):
        # if the server has not been created yet, do nothing
        if self.resource_id is None:
            return

        self.prepare_ports_for_replace()

    def restore_prev_rsrc(self, convergence=False):
        self.restore_ports_after_rollback(convergence=convergence)


def resource_mapping():
    return {
        'OS::Nova::Server': Server,
    }
