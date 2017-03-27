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
import six

cfg.CONF.import_opt('max_server_name_length', 'heat.common.config')

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine.clients import progress
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources import scheduler_hints as sh

LOG = logging.getLogger(__name__)


class Instance(resource.Resource, sh.SchedulerHintsMixin):

    PROPERTIES = (
        IMAGE_ID, INSTANCE_TYPE, KEY_NAME, AVAILABILITY_ZONE,
        DISABLE_API_TERMINATION, KERNEL_ID, MONITORING,
        PLACEMENT_GROUP_NAME, PRIVATE_IP_ADDRESS, RAM_DISK_ID,
        SECURITY_GROUPS, SECURITY_GROUP_IDS, NETWORK_INTERFACES,
        SOURCE_DEST_CHECK, SUBNET_ID, TAGS, NOVA_SCHEDULER_HINTS, TENANCY,
        USER_DATA, VOLUMES, BLOCK_DEVICE_MAPPINGS
    ) = (
        'ImageId', 'InstanceType', 'KeyName', 'AvailabilityZone',
        'DisableApiTermination', 'KernelId', 'Monitoring',
        'PlacementGroupName', 'PrivateIpAddress', 'RamDiskId',
        'SecurityGroups', 'SecurityGroupIds', 'NetworkInterfaces',
        'SourceDestCheck', 'SubnetId', 'Tags', 'NovaSchedulerHints', 'Tenancy',
        'UserData', 'Volumes', 'BlockDeviceMappings'
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    _NOVA_SCHEDULER_HINT_KEYS = (
        NOVA_SCHEDULER_HINT_KEY, NOVA_SCHEDULER_HINT_VALUE,
    ) = (
        'Key', 'Value',
    )

    _VOLUME_KEYS = (
        VOLUME_DEVICE, VOLUME_ID,
    ) = (
        'Device', 'VolumeId',
    )

    _BLOCK_DEVICE_MAPPINGS_KEYS = (
        DEVICE_NAME, EBS, NO_DEVICE, VIRTUAL_NAME,
    ) = (
        'DeviceName', 'Ebs', 'NoDevice', 'VirtualName',
    )

    _EBS_KEYS = (
        DELETE_ON_TERMINATION, IOPS, SNAPSHOT_ID, VOLUME_SIZE,
        VOLUME_TYPE,
    ) = (
        'DeleteOnTermination', 'Iops', 'SnapshotId', 'VolumeSize',
        'VolumeType'
    )

    ATTRIBUTES = (
        AVAILABILITY_ZONE_ATTR, PRIVATE_DNS_NAME, PUBLIC_DNS_NAME, PRIVATE_IP,
        PUBLIC_IP,
    ) = (
        'AvailabilityZone', 'PrivateDnsName', 'PublicDnsName', 'PrivateIp',
        'PublicIp',
    )

    properties_schema = {
        IMAGE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Glance image ID or name.'),
            constraints=[
                constraints.CustomConstraint('glance.image')
            ],
            required=True
        ),
        # AWS does not require InstanceType but Heat does because the nova
        # create api call requires a flavor
        INSTANCE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Nova instance type (flavor).'),
            required=True,
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('nova.flavor')
            ]
        ),
        KEY_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Optional Nova keypair name.'),
            constraints=[
                constraints.CustomConstraint("nova.keypair")
            ]
        ),
        AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _('Availability zone to launch the instance in.')
        ),
        DISABLE_API_TERMINATION: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        KERNEL_ID: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        MONITORING: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Not Implemented.'),
            implemented=False
        ),
        PLACEMENT_GROUP_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        PRIVATE_IP_ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        RAM_DISK_ID: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('Security group names to assign.')
        ),
        SECURITY_GROUP_IDS: properties.Schema(
            properties.Schema.LIST,
            _('Security group IDs to assign.')
        ),
        NETWORK_INTERFACES: properties.Schema(
            properties.Schema.LIST,
            _('Network interfaces to associate with instance.'),
            update_allowed=True
        ),
        SOURCE_DEST_CHECK: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Not Implemented.'),
            implemented=False
        ),
        SUBNET_ID: properties.Schema(
            properties.Schema.STRING,
            _('Subnet ID to launch instance in.'),
            update_allowed=True
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('Tags to attach to instance.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    TAG_KEY: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    TAG_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
            ),
            update_allowed=True
        ),
        NOVA_SCHEDULER_HINTS: properties.Schema(
            properties.Schema.LIST,
            _('Scheduler hints to pass to Nova (Heat extension).'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    NOVA_SCHEDULER_HINT_KEY: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    NOVA_SCHEDULER_HINT_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
            )
        ),
        TENANCY: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            constraints=[
                constraints.AllowedValues(['dedicated', 'default']),
            ],
            implemented=False
        ),
        USER_DATA: properties.Schema(
            properties.Schema.STRING,
            _('User data to pass to instance.')
        ),
        VOLUMES: properties.Schema(
            properties.Schema.LIST,
            _('Volumes to attach to instance.'),
            default=[],
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    VOLUME_DEVICE: properties.Schema(
                        properties.Schema.STRING,
                        _('The device where the volume is exposed on the '
                          'instance. This assignment may not be honored and '
                          'it is advised that the path '
                          '/dev/disk/by-id/virtio-<VolumeId> be used '
                          'instead.'),
                        required=True
                    ),
                    VOLUME_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('The ID of the volume to be attached.'),
                        required=True,
                        constraints=[
                            constraints.CustomConstraint('cinder.volume')
                        ]
                    ),
                }
            )
        ),
        BLOCK_DEVICE_MAPPINGS: properties.Schema(
            properties.Schema.LIST,
            _('Block device mappings to attach to instance.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    DEVICE_NAME: properties.Schema(
                        properties.Schema.STRING,
                        _('A device name where the volume will be '
                          'attached in the system at /dev/device_name.'
                          'e.g. vdb'),
                        required=True,
                    ),
                    EBS: properties.Schema(
                        properties.Schema.MAP,
                        _('The ebs volume to attach to the instance.'),
                        schema={
                            DELETE_ON_TERMINATION: properties.Schema(
                                properties.Schema.BOOLEAN,
                                _('Indicate whether the volume should be '
                                  'deleted when the instance is terminated.'),
                                default=True
                            ),
                            IOPS: properties.Schema(
                                properties.Schema.NUMBER,
                                _('The number of I/O operations per second '
                                  'that the volume supports.'),
                                implemented=False
                            ),
                            SNAPSHOT_ID: properties.Schema(
                                properties.Schema.STRING,
                                _('The ID of the snapshot to create '
                                  'a volume from.'),
                                constraints=[
                                    constraints.CustomConstraint(
                                        'cinder.snapshot')
                                ]
                            ),
                            VOLUME_SIZE: properties.Schema(
                                properties.Schema.STRING,
                                _('The size of the volume, in GB. Must be '
                                  'equal or greater than the size of the '
                                  'snapshot. It is safe to leave this blank '
                                  'and have the Compute service infer '
                                  'the size.'),
                            ),
                            VOLUME_TYPE: properties.Schema(
                                properties.Schema.STRING,
                                _('The volume type.'),
                                implemented=False
                            ),
                        },
                    ),
                    NO_DEVICE: properties.Schema(
                        properties.Schema.MAP,
                        _('The can be used to unmap a defined device.'),
                        implemented=False
                    ),
                    VIRTUAL_NAME: properties.Schema(
                        properties.Schema.STRING,
                        _('The name of the virtual device. The name must be '
                          'in the form ephemeralX where X is a number '
                          'starting from zero (0); for example, ephemeral0.'),
                        implemented=False
                    ),
                },
            ),
        ),
    }

    attributes_schema = {
        AVAILABILITY_ZONE_ATTR: attributes.Schema(
            _('The Availability Zone where the specified instance is '
              'launched.'),
            type=attributes.Schema.STRING
        ),
        PRIVATE_DNS_NAME: attributes.Schema(
            _('Private DNS name of the specified instance.'),
            type=attributes.Schema.STRING
        ),
        PUBLIC_DNS_NAME: attributes.Schema(
            _('Public DNS name of the specified instance.'),
            type=attributes.Schema.STRING
        ),
        PRIVATE_IP: attributes.Schema(
            _('Private IP address of the specified instance.'),
            type=attributes.Schema.STRING
        ),
        PUBLIC_IP: attributes.Schema(
            _('Public IP address of the specified instance.'),
            type=attributes.Schema.STRING
        ),
    }

    physical_resource_name_limit = cfg.CONF.max_server_name_length

    default_client_name = 'nova'

    def __init__(self, name, json_snippet, stack):
        super(Instance, self).__init__(name, json_snippet, stack)
        self.ipaddress = None

    def _set_ipaddress(self, networks):
        """Set IP address to self.ipaddress from a list of networks.

        Read the server's IP address from a list of networks provided by Nova.
        """
        # Just record the first ipaddress
        for n in sorted(networks, reverse=True):
            if len(networks[n]) > 0:
                self.ipaddress = networks[n][0]
                break

    def _ipaddress(self):
        """Return the server's IP address.

        Fetching it from Nova if necessary.
        """
        if self.ipaddress is None:
            self.ipaddress = self.client_plugin().server_to_ipaddress(
                self.resource_id)

        return self.ipaddress or '0.0.0.0'

    def _availability_zone(self):
        """Return Server's Availability Zone.

        Fetching it from Nova if necessary.
        """
        availability_zone = self.properties[self.AVAILABILITY_ZONE]
        if availability_zone is None:
            try:
                server = self.client().servers.get(self.resource_id)
            except Exception as e:
                self.client_plugin().ignore_not_found(e)
                return
        # Default to None if Nova's
        # OS-EXT-AZ:availability_zone extension is disabled
        return getattr(server, 'OS-EXT-AZ:availability_zone', None)

    def _resolve_attribute(self, name):
        res = None
        if name == self.AVAILABILITY_ZONE_ATTR:
            res = self._availability_zone()
        elif name in self.ATTRIBUTES[1:]:
            res = self._ipaddress()

        LOG.info('%(name)s._resolve_attribute(%(attname)s) == %(res)s',
                 {'name': self.name, 'attname': name, 'res': res})
        return six.text_type(res) if res else None

    def _port_data_delete(self):
        # delete the port data which implicit-created
        port_id = self.data().get('port_id')
        if port_id:
            with self.client_plugin('neutron').ignore_not_found:
                self.neutron().delete_port(port_id)
            self.data_delete('port_id')

    def _build_nics(self, network_interfaces,
                    security_groups=None, subnet_id=None):

        nics = None

        if network_interfaces:
            unsorted_nics = []
            for entry in network_interfaces:
                nic = (entry
                       if not isinstance(entry, six.string_types)
                       else {'NetworkInterfaceId': entry,
                             'DeviceIndex': len(unsorted_nics)})
                unsorted_nics.append(nic)
            sorted_nics = sorted(unsorted_nics,
                                 key=lambda nic: int(nic['DeviceIndex']))
            nics = [{'port-id': snic['NetworkInterfaceId']}
                    for snic in sorted_nics]
        else:
            # if SubnetId property in Instance, ensure subnet exists
            if subnet_id:
                neutronclient = self.neutron()
                network_id = self.client_plugin(
                    'neutron').network_id_from_subnet_id(subnet_id)
                # if subnet verified, create a port to use this subnet
                # if port is not created explicitly, nova will choose
                # the first subnet in the given network.
                if network_id:
                    fixed_ip = {'subnet_id': subnet_id}
                    props = {
                        'admin_state_up': True,
                        'network_id': network_id,
                        'fixed_ips': [fixed_ip]
                    }

                    if security_groups:
                        props['security_groups'] = self.client_plugin(
                            'neutron').get_secgroup_uuids(security_groups)

                    port = neutronclient.create_port({'port': props})['port']

                    # after create the port, set the port-id to
                    # resource data, so that the port can be deleted on
                    # instance delete.
                    self.data_set('port_id', port['id'])

                    nics = [{'port-id': port['id']}]

        return nics

    def _get_security_groups(self):
        security_groups = []
        for key in (self.SECURITY_GROUPS, self.SECURITY_GROUP_IDS):
            if self.properties.get(key) is not None:
                for sg in self.properties.get(key):
                    security_groups.append(sg)
        if not security_groups:
            security_groups = None
        return security_groups

    def _build_block_device_mapping(self, bdm):
        if not bdm:
            return None
        bdm_dict = {}
        for mapping in bdm:
            device_name = mapping.get(self.DEVICE_NAME)
            ebs = mapping.get(self.EBS)
            if ebs:
                mapping_parts = []
                snapshot_id = ebs.get(self.SNAPSHOT_ID)
                volume_size = ebs.get(self.VOLUME_SIZE)
                delete = ebs.get(self.DELETE_ON_TERMINATION)

                if snapshot_id:
                    mapping_parts.append(snapshot_id)
                    mapping_parts.append('snap')
                if volume_size:
                    mapping_parts.append(str(volume_size))
                else:
                    mapping_parts.append('')
                if delete is not None:
                    mapping_parts.append(str(delete))

                bdm_dict[device_name] = ':'.join(mapping_parts)

        return bdm_dict

    def _get_nova_metadata(self, properties):
        if properties is None or properties.get(self.TAGS) is None:
            return None

        return dict((tm[self.TAG_KEY], tm[self.TAG_VALUE])
                    for tm in properties[self.TAGS])

    def handle_create(self):
        security_groups = self._get_security_groups()

        userdata = self.properties[self.USER_DATA] or ''
        flavor = self.properties[self.INSTANCE_TYPE]
        availability_zone = self.properties[self.AVAILABILITY_ZONE]

        image_name = self.properties[self.IMAGE_ID]

        image_id = self.client_plugin(
            'glance').find_image_by_name_or_id(image_name)

        flavor_id = self.client_plugin().find_flavor_by_name_or_id(flavor)

        scheduler_hints = {}
        if self.properties[self.NOVA_SCHEDULER_HINTS]:
            for tm in self.properties[self.NOVA_SCHEDULER_HINTS]:
                # adopted from novaclient shell
                hint = tm[self.NOVA_SCHEDULER_HINT_KEY]
                hint_value = tm[self.NOVA_SCHEDULER_HINT_VALUE]
                if hint in scheduler_hints:
                    if isinstance(scheduler_hints[hint], six.string_types):
                        scheduler_hints[hint] = [scheduler_hints[hint]]
                    scheduler_hints[hint].append(hint_value)
                else:
                    scheduler_hints[hint] = hint_value
        else:
            scheduler_hints = None
        scheduler_hints = self._scheduler_hints(scheduler_hints)

        nics = self._build_nics(self.properties[self.NETWORK_INTERFACES],
                                security_groups=security_groups,
                                subnet_id=self.properties[self.SUBNET_ID])

        block_device_mapping = self._build_block_device_mapping(
            self.properties.get(self.BLOCK_DEVICE_MAPPINGS))

        server = None

        try:
            server = self.client().servers.create(
                name=self.physical_resource_name(),
                image=image_id,
                flavor=flavor_id,
                key_name=self.properties[self.KEY_NAME],
                security_groups=security_groups,
                userdata=self.client_plugin().build_userdata(
                    self.metadata_get(), userdata, 'ec2-user'),
                meta=self._get_nova_metadata(self.properties),
                scheduler_hints=scheduler_hints,
                nics=nics,
                availability_zone=availability_zone,
                block_device_mapping=block_device_mapping)
        finally:
            # Avoid a race condition where the thread could be cancelled
            # before the ID is stored
            if server is not None:
                self.resource_id_set(server.id)

        creator = progress.ServerCreateProgress(server.id)
        attachers = []
        for vol_id, device in self.volumes():
            attachers.append(progress.VolumeAttachProgress(self.resource_id,
                                                           vol_id, device))
        return creator, tuple(attachers)

    def check_create_complete(self, cookie):
        creator, attachers = cookie

        if not creator.complete:
            creator.complete = self.client_plugin()._check_active(
                creator.server_id, 'Instance')
            if creator.complete:
                server = self.client_plugin().get_server(creator.server_id)
                self._set_ipaddress(server.networks)
                # NOTE(pas-ha) small optimization,
                # return True if there are no volumes to attach
                # to save one check_create_complete call
                return not len(attachers)
            else:
                return False
        return self._attach_volumes(attachers)

    def _attach_volumes(self, attachers):
        for attacher in attachers:
            if not attacher.called:
                self.client_plugin().attach_volume(attacher.srv_id,
                                                   attacher.vol_id,
                                                   attacher.device)
                attacher.called = True
                return False

        for attacher in attachers:
            if not attacher.complete:
                attacher.complete = self.client_plugin(
                    'cinder').check_attach_volume_complete(attacher.vol_id)
                break
        out = all(attacher.complete for attacher in attachers)
        return out

    def volumes(self):
        """Return an iterator for all volumes that should be attached.

        Return an iterator over (volume_id, device) tuples for all volumes that
        should be attached to this instance.
        """
        volumes = self.properties[self.VOLUMES]

        return ((vol[self.VOLUME_ID],
                 vol[self.VOLUME_DEVICE]) for vol in volumes)

    def _remove_matched_ifaces(self, old_network_ifaces, new_network_ifaces):
        # find matches and remove them from old and new ifaces
        old_network_ifaces_copy = copy.deepcopy(old_network_ifaces)
        for iface in old_network_ifaces_copy:
            if iface in new_network_ifaces:
                new_network_ifaces.remove(iface)
                old_network_ifaces.remove(iface)

    def handle_check(self):
        server = self.client().servers.get(self.resource_id)
        if not self.client_plugin()._check_active(server, 'Instance'):
            raise exception.Error(_("Instance is not ACTIVE (was: %s)") %
                                  server.status.strip())

    def _update_instance_type(self, prop_diff):
        flavor = prop_diff[self.INSTANCE_TYPE]
        flavor_id = self.client_plugin().find_flavor_by_name_or_id(flavor)
        handler_args = {'args': (flavor_id,)}
        checker_args = {'args': (flavor_id,)}

        prg_resize = progress.ServerUpdateProgress(self.resource_id,
                                                   'resize',
                                                   handler_extra=handler_args,
                                                   checker_extra=checker_args)
        prg_verify = progress.ServerUpdateProgress(self.resource_id,
                                                   'verify_resize')
        return prg_resize, prg_verify

    def _update_network_interfaces(self, server, prop_diff):
        updaters = []
        new_network_ifaces = prop_diff.get(self.NETWORK_INTERFACES)
        old_network_ifaces = self.properties.get(self.NETWORK_INTERFACES)

        # if there is entrys in old_network_ifaces and new_network_ifaces,
        # remove the same entrys from old and new ifaces
        if old_network_ifaces and new_network_ifaces:
            # there are four situations:
            # 1.old includes new, such as: old = 2,3, new = 2
            # 2.new includes old, such as: old = 2,3, new = 1,2,3
            # 3.has overlaps, such as: old = 2,3, new = 1,2
            # 4.different, such as: old = 2,3, new = 1,4
            # detach unmatched ones in old, attach unmatched ones in new
            self._remove_matched_ifaces(old_network_ifaces,
                                        new_network_ifaces)
            if old_network_ifaces:
                old_nics = self._build_nics(old_network_ifaces)
                for nic in old_nics:
                    updaters.append(
                        progress.ServerUpdateProgress(
                            self.resource_id, 'interface_detach',
                            complete=True,
                            handler_extra={'args': (nic['port-id'],)})
                    )
            if new_network_ifaces:
                new_nics = self._build_nics(new_network_ifaces)
                for nic in new_nics:
                    handler_kwargs = {'port_id': nic['port-id']}
                    updaters.append(
                        progress.ServerUpdateProgress(
                            self.resource_id, 'interface_attach',
                            complete=True,
                            handler_extra={'kwargs': handler_kwargs})
                    )
        # if there is no change of 'NetworkInterfaces', do nothing,
        # keep the behavior as creation
        elif (old_network_ifaces and
                (self.NETWORK_INTERFACES not in prop_diff)):
            LOG.warning('There is no change of "%(net_interfaces)s" '
                        'for instance %(server)s, do nothing '
                        'when updating.',
                        {'net_interfaces': self.NETWORK_INTERFACES,
                         'server': self.resource_id})
        # if the interfaces not come from property 'NetworkInterfaces',
        # the situation is somewhat complex, so to detach the old ifaces,
        # and then attach the new ones.
        else:
            subnet_id = (prop_diff.get(self.SUBNET_ID) or
                         self.properties.get(self.SUBNET_ID))
            security_groups = self._get_security_groups()
            if not server:
                server = self.client().servers.get(self.resource_id)

            interfaces = server.interface_list()
            for iface in interfaces:
                updaters.append(
                    progress.ServerUpdateProgress(
                        self.resource_id, 'interface_detach',
                        complete=True,
                        handler_extra={'args': (iface.port_id,)})
                )
            # first to delete the port which implicit-created by heat
            self._port_data_delete()
            nics = self._build_nics(new_network_ifaces,
                                    security_groups=security_groups,
                                    subnet_id=subnet_id)
            # 'SubnetId' property is empty(or None) and
            # 'NetworkInterfaces' property is empty(or None),
            # _build_nics() will return nics = None,we should attach
            # first free port, according to similar behavior during
            # instance creation
            if not nics:
                updaters.append(
                    progress.ServerUpdateProgress(
                        self.resource_id, 'interface_attach', complete=True)
                )
            else:
                for nic in nics:
                    updaters.append(
                        progress.ServerUpdateProgress(
                            self.resource_id, 'interface_attach',
                            complete=True,
                            handler_extra={'kwargs':
                                           {'port_id': nic['port-id']}})
                    )

        return updaters

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if tmpl_diff.metadata_changed():
            self.metadata_set(json_snippet.metadata())
        updaters = []
        server = None
        if self.TAGS in prop_diff:
            server = self.client().servers.get(self.resource_id)
            self.client_plugin().meta_update(
                server, self._get_nova_metadata(prop_diff))

        if self.INSTANCE_TYPE in prop_diff:
            updaters.extend(self._update_instance_type(prop_diff))

        if (self.NETWORK_INTERFACES in prop_diff or
                self.SUBNET_ID in prop_diff):
            updaters.extend(self._update_network_interfaces(server, prop_diff))

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
        return all(prg.complete for prg in updaters)

    def metadata_update(self, new_metadata=None):
        """Refresh the metadata if new_metadata is None."""
        if new_metadata is None:
            self.metadata_set(self.t.metadata())

    def validate(self):
        """Validate any of the provided params."""
        res = super(Instance, self).validate()
        if res:
            return res

        # check validity of security groups vs. network interfaces
        security_groups = self._get_security_groups()
        network_interfaces = self.properties.get(self.NETWORK_INTERFACES)
        if security_groups and network_interfaces:
            raise exception.ResourcePropertyConflict(
                '/'.join([self.SECURITY_GROUPS, self.SECURITY_GROUP_IDS]),
                self.NETWORK_INTERFACES)

        # check bdm property
        # now we don't support without snapshot_id in bdm
        bdm = self.properties.get(self.BLOCK_DEVICE_MAPPINGS)
        if bdm:
            for mapping in bdm:
                ebs = mapping.get(self.EBS)
                if ebs:
                    snapshot_id = ebs.get(self.SNAPSHOT_ID)
                    if not snapshot_id:
                        msg = _("SnapshotId is missing, this is required "
                                "when specifying BlockDeviceMappings.")
                        raise exception.StackValidationFailed(message=msg)
                else:
                    msg = _("Ebs is missing, this is required "
                            "when specifying BlockDeviceMappings.")
                    raise exception.StackValidationFailed(message=msg)

        subnet_id = self.properties.get(self.SUBNET_ID)
        if network_interfaces and subnet_id:
            # consider the old templates, we only to log to warn user
            # NetworkInterfaces has higher priority than SubnetId
            LOG.warning('"%(subnet)s" will be ignored if specified '
                        '"%(net_interfaces)s". So if you specified the '
                        '"%(net_interfaces)s" property, '
                        'do not specify "%(subnet)s" property.',
                        {'subnet': self.SUBNET_ID,
                         'net_interfaces': self.NETWORK_INTERFACES})

    def handle_delete(self):
        # make sure to delete the port which implicit-created by heat
        self._port_data_delete()

        if self.resource_id is None:
            return
        try:
            self.client().servers.delete(self.resource_id)
        except Exception as e:
            self.client_plugin().ignore_not_found(e)
            return
        return self.resource_id

    def check_delete_complete(self, server_id):
        if not server_id:
            return True
        return self.client_plugin().check_delete_server_complete(server_id)

    def handle_suspend(self):
        """Suspend an instance.

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
                raise exception.NotFound(_('Failed to find instance %s') %
                                         self.resource_id)
            else:
                raise
        else:
            # if the instance has been suspended successful,
            # no need to suspend again
            if self.client_plugin().get_status(server) != 'SUSPENDED':
                LOG.debug("suspending instance %s", self.resource_id)
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
                result=_('Suspend of instance %s failed') % server.name,
                resource_status=status)
            raise exc

    def handle_resume(self):
        """Resume an instance.

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
                raise exception.NotFound(_('Failed to find instance %s') %
                                         self.resource_id)
            else:
                raise
        else:
            # if the instance has been resumed successful,
            # no need to resume again
            if self.client_plugin().get_status(server) != 'ACTIVE':
                LOG.debug("resuming instance %s", self.resource_id)
                server.resume()
            return server.id

    def check_resume_complete(self, server_id):
        return self.client_plugin()._check_active(server_id, 'Instance')


def resource_mapping():
    return {
        'AWS::EC2::Instance': Instance,
    }
