
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

from oslo.config import cfg
import uuid

from heat.common import exception
from heat.db import api as db_api
from heat.engine import clients
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.neutron import subnet
from heat.engine.resources import nova_utils
from heat.engine.resources.software_config import software_config as sc
from heat.engine import scheduler
from heat.engine import stack_user
from heat.engine import support
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging
from heat.openstack.common import uuidutils

cfg.CONF.import_opt('instance_user', 'heat.common.config')

logger = logging.getLogger(__name__)


class Server(stack_user.StackUser):

    PROPERTIES = (
        NAME, IMAGE, BLOCK_DEVICE_MAPPING, FLAVOR,
        FLAVOR_UPDATE_POLICY, IMAGE_UPDATE_POLICY, KEY_NAME,
        ADMIN_USER, AVAILABILITY_ZONE, SECURITY_GROUPS, NETWORKS,
        SCHEDULER_HINTS, METADATA, USER_DATA_FORMAT, USER_DATA,
        RESERVATION_ID, CONFIG_DRIVE, DISK_CONFIG, PERSONALITY,
        ADMIN_PASS, SOFTWARE_CONFIG_TRANSPORT
    ) = (
        'name', 'image', 'block_device_mapping', 'flavor',
        'flavor_update_policy', 'image_update_policy', 'key_name',
        'admin_user', 'availability_zone', 'security_groups', 'networks',
        'scheduler_hints', 'metadata', 'user_data_format', 'user_data',
        'reservation_id', 'config_drive', 'diskConfig', 'personality',
        'admin_pass', 'software_config_transport'
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

    _NETWORK_KEYS = (
        NETWORK_UUID, NETWORK_ID, NETWORK_FIXED_IP, NETWORK_PORT,
    ) = (
        'uuid', 'network', 'fixed_ip', 'port',
    )

    _SOFTWARE_CONFIG_FORMATS = (
        HEAT_CFNTOOLS, RAW, SOFTWARE_CONFIG
    ) = (
        'HEAT_CFNTOOLS', 'RAW', 'SOFTWARE_CONFIG'
    )

    _SOFTWARE_CONFIG_TRANSPORTS = (
        POLL_SERVER_CFN, POLL_SERVER_HEAT
    ) = (
        'POLL_SERVER_CFN', 'POLL_SERVER_HEAT'
    )

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
                          'provided.')
                    ),
                    BLOCK_DEVICE_MAPPING_SNAPSHOT_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('The ID of the snapshot to create a volume '
                          'from.')
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
        FLAVOR: properties.Schema(
            properties.Schema.STRING,
            _('The ID or name of the flavor to boot onto.'),
            required=True,
            update_allowed=True
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
              'requesting a server rebuild or by replacing the entire server'),
            default='REPLACE',
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
            _('Name of the administrative user to use on the server. '
              'This property will be removed from Juno in favor of the '
              'default cloud-init user set up for each image (e.g. "ubuntu" '
              'for Ubuntu 12.04+, "fedora" for Fedora 19+ and "cloud-user" '
              'for CentOS/RHEL 6.5).'),
            support_status=support.SupportStatus(status=support.DEPRECATED)
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
                            support.DEPRECATED,
                            _('Use property %s.') % NETWORK_ID)
                    ),
                    NETWORK_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('Name or ID of network to create a port on.')
                    ),
                    NETWORK_FIXED_IP: properties.Schema(
                        properties.Schema.STRING,
                        _('Fixed IP address to specify for the port '
                          'created on the requested network.')
                    ),
                    NETWORK_PORT: properties.Schema(
                        properties.Schema.STRING,
                        _('ID of an existing port to associate with this '
                          'server.')
                    ),
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
              'keys and values must be 255 characters or less.  Non-string '
              'values will be serialized to JSON (and the serialized '
              'string must be 255 characters or less).'),
            update_allowed=True
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
            default=HEAT_CFNTOOLS,
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
              'credentials.'),
            default=POLL_SERVER_CFN,
            constraints=[
                constraints.AllowedValues(_SOFTWARE_CONFIG_TRANSPORTS),
            ]
        ),
        USER_DATA: properties.Schema(
            properties.Schema.STRING,
            _('User data script to be executed by cloud-init.'),
            default=''
        ),
        RESERVATION_ID: properties.Schema(
            properties.Schema.STRING,
            _('A UUID for the set of servers being requested.')
        ),
        CONFIG_DRIVE: properties.Schema(
            properties.Schema.STRING,
            _('value for config drive either boolean, or volume-id.')
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
            default={}
        ),
        ADMIN_PASS: properties.Schema(
            properties.Schema.STRING,
            _('The administrator password for the server.'),
            required=False,
            update_allowed=True
        ),
    }

    attributes_schema = {
        'show': _('A dict of all server details as returned by the API.'),
        'addresses': _('A dict of all network addresses with corresponding'
                       'port_id.'),
        'networks': _('A dict of assigned network addresses of the form: '
                      '{"public": [ip1, ip2...], "private": [ip3, ip4]}.'),
        'first_address': _('Convenience attribute to fetch the first '
                           'assigned network address, or an '
                           'empty string if nothing has been assigned '
                           'at this time. Result may not be predictable '
                           'if the server has addresses from more than one '
                           'network.'),
        'instance_name': _('AWS compatible instance name.'),
        'accessIPv4': _('The manually assigned alternative public IPv4 '
                        'address of the server.'),
        'accessIPv6': _('The manually assigned alternative public IPv6 '
                        'address of the server.'),
    }

    update_allowed_keys = ('Metadata', 'Properties')

    # Server host name limit to 53 characters by due to typical default
    # linux HOST_NAME_MAX of 64, minus the .novalocal appended to the name
    physical_resource_name_limit = 53

    def __init__(self, name, json_snippet, stack):
        super(Server, self).__init__(name, json_snippet, stack)
        if self.user_data_software_config():
            self._register_access_key()

    def physical_resource_name(self):
        name = self.properties.get(self.NAME)
        if name:
            return name

        return super(Server, self).physical_resource_name()

    def _personality(self):
        # This method is overridden by the derived CloudServer resource
        return self.properties.get(self.PERSONALITY)

    def _key_name(self):
        # This method is overridden by the derived CloudServer resource
        return self.properties.get(self.KEY_NAME)

    @staticmethod
    def _get_deployments_metadata(heatclient, server_id):
        return heatclient.software_deployments.metadata(
            server_id=server_id)

    def _build_deployments_metadata(self):
        meta = {}
        if self.transport_poll_server_heat():
            meta['os-collect-config'] = {'heat': {
                'user_id': self._get_user_id(),
                'password': self.password,
                'auth_url': self.context.auth_url,
                'project_id': self.stack.stack_user_project_id,
                'stack_id': self.stack.identifier().stack_path(),
                'resource_name': self.name}
            }
        elif self.transport_poll_server_cfn():
            meta['os-collect-config'] = {'cfn': {
                'metadata_url': '%s/v1/' % cfg.CONF.heat_metadata_server_url,
                'access_key_id': self.access_key,
                'secret_access_key': self.secret_key,
                'stack_name': self.stack.name,
                'path': '%s.Metadata' % self.name}
            }

        deployments = []
        # cannot query the deployments if the nova server does
        # not exist yet
        if self.resource_id:
            deployments = self._get_deployments_metadata(
                self.heat(), self.resource_id)
        meta['deployments'] = deployments
        return meta

    def _register_access_key(self):
        '''
        Access is limited to this resource, which created the keypair
        '''
        def access_allowed(resource_name):
            return resource_name == self.name

        if self.transport_poll_server_cfn():
            self.stack.register_access_allowed_handler(
                self.access_key, access_allowed)
        elif self.transport_poll_server_heat():
            self.stack.register_access_allowed_handler(
                self._get_user_id(), access_allowed)

    def _create_transport_credentials(self):
        if self.transport_poll_server_cfn():
            self._create_user()
            self._create_keypair()

        elif self.transport_poll_server_heat():
            self.password = uuid.uuid4().hex
            self._create_user()

        self._register_access_key()

    @property
    def access_key(self):
        try:
            return db_api.resource_data_get(self, 'access_key')
        except exception.NotFound:
            pass

    @property
    def secret_key(self):
        try:
            return db_api.resource_data_get(self, 'secret_key')
        except exception.NotFound:
            pass

    @property
    def password(self):
        try:
            return db_api.resource_data_get(self, 'password')
        except exception.NotFound:
            pass

    @password.setter
    def password(self, password):
        try:
            if password is None:
                db_api.resource_data_delete(self, 'password')
            else:
                db_api.resource_data_set(self, 'password', password, True)
        except exception.NotFound:
            pass

    @property
    def metadata(self):
        if self.user_data_software_config():
            return self._build_deployments_metadata()
        else:
            return self._metadata

    @metadata.setter
    def metadata(self, metadata):
        if not self.user_data_software_config():
            self._metadata = metadata

    def user_data_raw(self):
        return self.properties.get(self.USER_DATA_FORMAT) == self.RAW

    def user_data_software_config(self):
        return self.properties.get(
            self.USER_DATA_FORMAT) == self.SOFTWARE_CONFIG

    def transport_poll_server_cfn(self):
        return self.properties.get(
            self.SOFTWARE_CONFIG_TRANSPORT) == self.POLL_SERVER_CFN

    def transport_poll_server_heat(self):
        return self.properties.get(
            self.SOFTWARE_CONFIG_TRANSPORT) == self.POLL_SERVER_HEAT

    def handle_create(self):
        security_groups = self.properties.get(self.SECURITY_GROUPS)

        user_data_format = self.properties.get(self.USER_DATA_FORMAT)
        ud_content = self.properties.get(self.USER_DATA)
        if self.user_data_software_config() or self.user_data_raw():
            if uuidutils.is_uuid_like(ud_content):
                # attempt to load the userdata from software config
                try:
                    ud_content = sc.SoftwareConfig.get_software_config(
                        self.heat(), ud_content)
                except exception.SoftwareConfigMissing:
                    # no config was found, so do not modify the user_data
                    pass

        if self.user_data_software_config():
            self._create_transport_credentials()

        if self.properties[self.ADMIN_USER]:
            instance_user = self.properties[self.ADMIN_USER]
        elif cfg.CONF.instance_user:
            instance_user = cfg.CONF.instance_user
        else:
            instance_user = None

        userdata = nova_utils.build_userdata(
            self,
            ud_content,
            instance_user=instance_user,
            user_data_format=user_data_format)

        flavor = self.properties[self.FLAVOR]
        availability_zone = self.properties[self.AVAILABILITY_ZONE]

        image = self.properties.get(self.IMAGE)
        if image:
            image = nova_utils.get_image_id(self.nova(), image)

        flavor_id = nova_utils.get_flavor_id(self.nova(), flavor)

        instance_meta = self.properties.get(self.METADATA)
        if instance_meta is not None:
            instance_meta = nova_utils.meta_serialize(instance_meta)

        scheduler_hints = self.properties.get(self.SCHEDULER_HINTS)
        nics = self._build_nics(self.properties.get(self.NETWORKS))
        block_device_mapping = self._build_block_device_mapping(
            self.properties.get(self.BLOCK_DEVICE_MAPPING))
        reservation_id = self.properties.get(self.RESERVATION_ID)
        config_drive = self.properties.get(self.CONFIG_DRIVE)
        disk_config = self.properties.get(self.DISK_CONFIG)
        admin_pass = self.properties.get(self.ADMIN_PASS) or None

        server = None
        try:
            server = self.nova().servers.create(
                name=self.physical_resource_name(),
                image=image,
                flavor=flavor_id,
                key_name=self._key_name(),
                security_groups=security_groups,
                userdata=userdata,
                meta=instance_meta,
                scheduler_hints=scheduler_hints,
                nics=nics,
                availability_zone=availability_zone,
                block_device_mapping=block_device_mapping,
                reservation_id=reservation_id,
                config_drive=config_drive,
                disk_config=disk_config,
                files=self._personality(),
                admin_pass=admin_pass)
        finally:
            # Avoid a race condition where the thread could be cancelled
            # before the ID is stored
            if server is not None:
                self.resource_id_set(server.id)

        return server

    def check_create_complete(self, server):
        return self._check_active(server)

    def _check_active(self, server):

        if server.status != 'ACTIVE':
            nova_utils.refresh_server(server)

        # Some clouds append extra (STATUS) strings to the status
        short_server_status = server.status.split('(')[0]
        if short_server_status in nova_utils.deferred_server_statuses:
            return False
        elif server.status == 'ACTIVE':
            return True
        elif server.status == 'ERROR':
            exc = exception.Error(_('Creation of server %s failed.') %
                                  server.name)
            raise exc
        else:
            exc = exception.Error(_('Creation of server %(server)s failed '
                                    'with unknown status: %(status)s') %
                                  dict(server=server.name,
                                       status=server.status))
            raise exc

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
            if volume_size or delete:
                mapping_parts.append(str(volume_size or 0))
            if delete:
                mapping_parts.append(str(delete))

            device_name = mapping.get(cls.BLOCK_DEVICE_MAPPING_DEVICE_NAME)
            bdm_dict[device_name] = ':'.join(mapping_parts)

        return bdm_dict

    def _build_nics(self, networks):
        if not networks:
            return None

        nics = []

        for net_data in networks:
            nic_info = {}
            if net_data.get(self.NETWORK_UUID):
                nic_info['net-id'] = net_data[self.NETWORK_UUID]
            label_or_uuid = net_data.get(self.NETWORK_ID)
            if label_or_uuid:
                if uuidutils.is_uuid_like(label_or_uuid):
                    nic_info['net-id'] = label_or_uuid
                else:
                    network = self.nova().networks.find(label=label_or_uuid)
                    nic_info['net-id'] = network.id
            if net_data.get(self.NETWORK_FIXED_IP):
                nic_info['v4-fixed-ip'] = net_data[self.NETWORK_FIXED_IP]
            if net_data.get(self.NETWORK_PORT):
                nic_info['port-id'] = net_data[self.NETWORK_PORT]
            nics.append(nic_info)
        return nics

    def _add_port_for_address(self, server):
        nets = copy.deepcopy(server.addresses)
        ifaces = server.interface_list()
        ip_mac_mapping_on_port_id = dict(((iface.fixed_ips[0]['ip_address'],
                                           iface.mac_addr), iface.port_id)
                                         for iface in ifaces)
        for net_name in nets:
            for addr in nets[net_name]:
                addr['port'] = ip_mac_mapping_on_port_id.get(
                    (addr['addr'], addr['OS-EXT-IPS-MAC:mac_addr']))
        return nets

    def _resolve_attribute(self, name):
        if name == 'first_address':
            return nova_utils.server_to_ipaddress(
                self.nova(), self.resource_id) or ''
        try:
            server = self.nova().servers.get(self.resource_id)
        except clients.novaclient.exceptions.NotFound as ex:
            logger.warn(_('Instance (%(server)s) not found: %(ex)s') % {
                        'server': self.resource_id, 'ex': str(ex)})
            return ''
        if name == 'addresses':
            return self._add_port_for_address(server)
        if name == 'networks':
            return server.networks
        if name == 'instance_name':
            return server._info.get('OS-EXT-SRV-ATTR:instance_name')
        if name == 'accessIPv4':
            return server.accessIPv4
        if name == 'accessIPv6':
            return server.accessIPv6
        if name == 'show':
            return server._info

    def add_dependencies(self, deps):
        super(Server, self).add_dependencies(deps)
        # Depend on any Subnet in this template with the same
        # network_id as the networks attached to this server.
        # It is not known which subnet a server might be assigned
        # to so all subnets in a network should be created before
        # the servers in that network.
        for res in self.stack.itervalues():
            if (res.has_interface('OS::Neutron::Subnet')):
                subnet_net = res.properties.get(subnet.Subnet.NETWORK_ID)
                for net in self.properties.get(self.NETWORKS):
                    # we do not need to worry about NETWORK_ID values which are
                    # names instead of UUIDs since these were not created
                    # by this stack
                    net_id = (net.get(self.NETWORK_ID) or
                              net.get(self.NETWORK_UUID))
                    if net_id and net_id == subnet_net:
                        deps += (self, res)
                        break

    def _get_network_matches(self, old_networks, new_networks):
        # make new_networks similar on old_networks
        for net in new_networks:
            for key in ('port', 'network', 'fixed_ip'):
                net.setdefault(key)
        # find matches and remove them from old and new networks
        not_updated_networks = []
        for net in old_networks:
            net.pop('uuid', None)
            if net in new_networks:
                new_networks.remove(net)
                not_updated_networks.append(net)
        for net in not_updated_networks:
            old_networks.remove(net)
        return not_updated_networks

    def update_networks_matching_iface_port(self, nets, interfaces):

        def find_equal(port, net_id, ip, nets):
            for net in nets:
                if (net.get('port') == port or
                        (net.get('fixed_ip') == ip and
                            net.get('network') == net_id)):
                    return net

        def find_poor_net(net_id, nets):
            for net in nets:
                if net == {'port': None, 'network': net_id, 'fixed_ip': None}:
                    return net

        for iface in interfaces:
            # get interface properties
            props = {'port': iface.port_id,
                     'net_id': iface.net_id,
                     'ip': iface.fixed_ips[0]['ip_address'],
                     'nets': nets}
            # try to match by port or network_id with fixed_ip
            net = find_equal(**props)
            if net is not None:
                net['port'] = props['port']
                continue
            # find poor net that has only network_id
            net = find_poor_net(props['net_id'], nets)
            if net is not None:
                net['port'] = props['port']

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if 'Metadata' in tmpl_diff:
            self.metadata = tmpl_diff['Metadata']

        checkers = []
        server = None

        if self.METADATA in prop_diff:
            server = self.nova().servers.get(self.resource_id)
            nova_utils.meta_update(self.nova(),
                                   server,
                                   prop_diff[self.METADATA])

        if self.FLAVOR in prop_diff:

            flavor_update_policy = (
                prop_diff.get(self.FLAVOR_UPDATE_POLICY) or
                self.properties.get(self.FLAVOR_UPDATE_POLICY))

            if flavor_update_policy == 'REPLACE':
                raise resource.UpdateReplace(self.name)

            flavor = prop_diff[self.FLAVOR]
            flavor_id = nova_utils.get_flavor_id(self.nova(), flavor)
            if not server:
                server = self.nova().servers.get(self.resource_id)
            checker = scheduler.TaskRunner(nova_utils.resize, server, flavor,
                                           flavor_id)
            checkers.append(checker)

        if self.IMAGE in prop_diff:
            image_update_policy = (
                prop_diff.get(self.IMAGE_UPDATE_POLICY) or
                self.properties.get(self.IMAGE_UPDATE_POLICY))
            if image_update_policy == 'REPLACE':
                raise resource.UpdateReplace(self.name)
            image = prop_diff[self.IMAGE]
            image_id = nova_utils.get_image_id(self.nova(), image)
            if not server:
                server = self.nova().servers.get(self.resource_id)
            preserve_ephemeral = (
                image_update_policy == 'REBUILD_PRESERVE_EPHEMERAL')
            checker = scheduler.TaskRunner(
                nova_utils.rebuild, server, image_id,
                preserve_ephemeral=preserve_ephemeral)
            checkers.append(checker)

        if self.NAME in prop_diff:
            if not server:
                server = self.nova().servers.get(self.resource_id)
            nova_utils.rename(server, prop_diff[self.NAME])

        if self.NETWORKS in prop_diff:
            new_networks = prop_diff.get(self.NETWORKS)
            attach_first_free_port = False
            if not new_networks:
                new_networks = []
                attach_first_free_port = True
            old_networks = self.properties.get(self.NETWORKS)

            if not server:
                server = self.nova().servers.get(self.resource_id)
            interfaces = server.interface_list()

            # if old networks is None, it means that the server got first
            # free port. so we should detach this interface.
            if old_networks is None:
                for iface in interfaces:
                    checker = scheduler.TaskRunner(server.interface_detach,
                                                   iface.port_id)
                    checkers.append(checker)
            # if we have any information in networks field, we should:
            # 1. find similar networks, if they exist
            # 2. remove these networks from new_networks and old_networks
            #    lists
            # 3. detach unmatched networks, which were present in old_networks
            # 4. attach unmatched networks, which were present in new_networks
            else:
                # remove not updated networks from old and new networks lists,
                # also get list these networks
                not_updated_networks = \
                    self._get_network_matches(old_networks, new_networks)

                self.update_networks_matching_iface_port(
                    old_networks + not_updated_networks, interfaces)

                # according to nova interface-detach command detached port
                # will be deleted
                for net in old_networks:
                    checker = scheduler.TaskRunner(server.interface_detach,
                                                   net.get('port'))
                    checkers.append(checker)

            # attach section similar for both variants that
            # were mentioned above

            for net in new_networks:
                if net.get('port'):
                    checker = scheduler.TaskRunner(server.interface_attach,
                                                   net['port'], None, None)
                    checkers.append(checker)
                elif net.get('network'):
                    checker = scheduler.TaskRunner(server.interface_attach,
                                                   None, net['network'],
                                                   net.get('fixed_ip'))
                    checkers.append(checker)

            # if new_networks is None, we should attach first free port,
            # according to similar behavior during instance creation
            if attach_first_free_port:
                checker = scheduler.TaskRunner(server.interface_attach,
                                               None, None, None)
                checkers.append(checker)

        # Optimization: make sure the first task is started before
        # check_update_complete.
        if checkers:
            checkers[0].start()

        return checkers

    def check_update_complete(self, checkers):
        '''Push all checkers to completion in list order.'''
        for checker in checkers:
            if not checker.started():
                checker.start()
            if not checker.step():
                return False
        return True

    def metadata_update(self, new_metadata=None):
        '''
        Refresh the metadata if new_metadata is None
        '''
        if new_metadata is None:
            self.metadata = self.parsed_template('Metadata')

    @staticmethod
    def _check_maximum(count, maximum, msg):
        '''
        Check a count against a maximum, unless maximum is -1 which indicates
        that there is no limit
        '''
        if maximum != -1 and count > maximum:
            raise exception.StackValidationFailed(message=msg)

    def validate(self):
        '''
        Validate any of the provided params
        '''
        super(Server, self).validate()

        # either volume_id or snapshot_id needs to be specified, but not both
        # for block device mapping.
        bdm = self.properties.get(self.BLOCK_DEVICE_MAPPING) or []
        bootable_vol = False
        for mapping in bdm:
            device_name = mapping[self.BLOCK_DEVICE_MAPPING_DEVICE_NAME]
            if device_name == 'vda':
                bootable_vol = True

            volume_id = mapping.get(self.BLOCK_DEVICE_MAPPING_VOLUME_ID)
            snapshot_id = mapping.get(self.BLOCK_DEVICE_MAPPING_SNAPSHOT_ID)
            if volume_id and snapshot_id:
                raise exception.ResourcePropertyConflict(
                    self.BLOCK_DEVICE_MAPPING_VOLUME_ID,
                    self.BLOCK_DEVICE_MAPPING_SNAPSHOT_ID)
            if not volume_id and not snapshot_id:
                msg = _('Either volume_id or snapshot_id must be specified for'
                        ' device mapping %s') % device_name
                raise exception.StackValidationFailed(message=msg)

        # make sure the image exists if specified.
        image = self.properties.get(self.IMAGE)
        if not image and not bootable_vol:
            msg = _('Neither image nor bootable volume is specified for'
                    ' instance %s') % self.name
            raise exception.StackValidationFailed(message=msg)

        # network properties 'uuid' and 'network' shouldn't be used
        # both at once for all networks
        networks = self.properties.get(self.NETWORKS) or []
        # record if any networks include explicit ports
        networks_with_port = False
        for network in networks:
            networks_with_port = networks_with_port or \
                network.get(self.NETWORK_PORT)
            if network.get(self.NETWORK_UUID) and network.get(self.NETWORK_ID):
                msg = _('Properties "%(uuid)s" and "%(id)s" are both set '
                        'to the network "%(network)s" for the server '
                        '"%(server)s". The "%(uuid)s" property is deprecated. '
                        'Use only "%(id)s" property.'
                        '') % dict(uuid=self.NETWORK_UUID,
                                   id=self.NETWORK_ID,
                                   network=network[self.NETWORK_ID],
                                   server=self.name)
                raise exception.StackValidationFailed(message=msg)
            elif network.get(self.NETWORK_UUID):
                logger.info(_('For the server "%(server)s" the "%(uuid)s" '
                              'property is set to network "%(network)s". '
                              '"%(uuid)s" property is deprecated. Use '
                              '"%(id)s"  property instead.'
                              '') % dict(uuid=self.NETWORK_UUID,
                                         id=self.NETWORK_ID,
                                         network=network[self.NETWORK_ID],
                                         server=self.name))

        # retrieve provider's absolute limits if it will be needed
        metadata = self.properties.get(self.METADATA)
        personality = self._personality()
        if metadata is not None or personality:
            limits = nova_utils.absolute_limits(self.nova())

        # if 'security_groups' present for the server and explict 'port'
        # in one or more entries in 'networks', raise validation error
        if networks_with_port and self.properties.get(self.SECURITY_GROUPS):
            raise exception.ResourcePropertyConflict(
                self.SECURITY_GROUPS,
                "/".join([self.NETWORKS, self.NETWORK_PORT]))

        # verify that the number of metadata entries is not greater
        # than the maximum number allowed in the provider's absolute
        # limits
        if metadata is not None:
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
                self._check_maximum(len(bytes(contents)),
                                    limits['maxPersonalitySize'], msg)

    def handle_delete(self):
        '''
        Delete a server, blocking until it is disposed by OpenStack
        '''
        if self.resource_id is None:
            return

        if self.user_data_software_config():
            self._delete_user()

        try:
            server = self.nova().servers.get(self.resource_id)
        except clients.novaclient.exceptions.NotFound:
            pass
        else:
            delete = scheduler.TaskRunner(nova_utils.delete_server, server)
            delete(wait_time=0.2)

        self.resource_id_set(None)

    def handle_suspend(self):
        '''
        Suspend a server - note we do not wait for the SUSPENDED state,
        this is polled for by check_suspend_complete in a similar way to the
        create logic so we can take advantage of coroutines
        '''
        if self.resource_id is None:
            raise exception.Error(_('Cannot suspend %s, resource_id not set') %
                                  self.name)

        try:
            server = self.nova().servers.get(self.resource_id)
        except clients.novaclient.exceptions.NotFound:
            raise exception.NotFound(_('Failed to find server %s') %
                                     self.resource_id)
        else:
            logger.debug(_('suspending server %s') % self.resource_id)
            # We want the server.suspend to happen after the volume
            # detachement has finished, so pass both tasks and the server
            suspend_runner = scheduler.TaskRunner(server.suspend)
            return server, suspend_runner

    def check_suspend_complete(self, cookie):
        server, suspend_runner = cookie

        if not suspend_runner.started():
            suspend_runner.start()

        if suspend_runner.done():
            if server.status == 'SUSPENDED':
                return True

            nova_utils.refresh_server(server)
            logger.debug(_('%(name)s check_suspend_complete status '
                         '= %(status)s') % {
                             'name': self.name, 'status': server.status})
            if server.status in list(nova_utils.deferred_server_statuses +
                                     ['ACTIVE']):
                return server.status == 'SUSPENDED'
            else:
                exc = exception.Error(_('Suspend of server %(server)s failed '
                                        'with unknown status: %(status)s') %
                                      dict(server=server.name,
                                           status=server.status))
                raise exc

    def handle_resume(self):
        '''
        Resume a server - note we do not wait for the ACTIVE state,
        this is polled for by check_resume_complete in a similar way to the
        create logic so we can take advantage of coroutines
        '''
        if self.resource_id is None:
            raise exception.Error(_('Cannot resume %s, resource_id not set') %
                                  self.name)

        try:
            server = self.nova().servers.get(self.resource_id)
        except clients.novaclient.exceptions.NotFound:
            raise exception.NotFound(_('Failed to find server %s') %
                                     self.resource_id)
        else:
            logger.debug(_('resuming server %s') % self.resource_id)
            server.resume()
            return server

    def check_resume_complete(self, server):
        return self._check_active(server)


class FlavorConstraint(object):

    def validate(self, value, context):
        nova_client = clients.Clients(context).nova()
        try:
            nova_utils.get_flavor_id(nova_client, value)
        except exception.FlavorMissing:
            return False
        else:
            return True


def constraint_mapping():
    return {'nova.flavor': FlavorConstraint}


def resource_mapping():
    return {
        'OS::Nova::Server': Server,
    }
