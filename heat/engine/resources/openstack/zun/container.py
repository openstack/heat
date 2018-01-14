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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine.clients import progress
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.nova import server_network_mixin
from heat.engine import support
from heat.engine import translation


class Container(resource.Resource,
                server_network_mixin.ServerNetworkMixin):
    """A resource that creates a Zun Container.

    This resource creates a Zun container.
    """

    support_status = support.SupportStatus(version='9.0.0')

    PROPERTIES = (
        NAME, IMAGE, COMMAND, CPU, MEMORY,
        ENVIRONMENT, WORKDIR, LABELS, IMAGE_PULL_POLICY,
        RESTART_POLICY, INTERACTIVE, IMAGE_DRIVER, HINTS,
        HOSTNAME, SECURITY_GROUPS, MOUNTS, NETWORKS,
    ) = (
        'name', 'image', 'command', 'cpu', 'memory',
        'environment', 'workdir', 'labels', 'image_pull_policy',
        'restart_policy', 'interactive', 'image_driver', 'hints',
        'hostname', 'security_groups', 'mounts', 'networks',
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

    _MOUNT_KEYS = (
        VOLUME_ID, MOUNT_PATH, VOLUME_SIZE
    ) = (
        'volume_id', 'mount_path', 'volume_size',
    )

    ATTRIBUTES = (
        NAME, ADDRESSES
    ) = (
        'name', 'addresses'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the container.'),
            update_allowed=True
        ),
        IMAGE: properties.Schema(
            properties.Schema.STRING,
            _('Name or ID of the image.'),
            required=True
        ),
        COMMAND: properties.Schema(
            properties.Schema.STRING,
            _('Send command to the container.'),
        ),
        CPU: properties.Schema(
            properties.Schema.NUMBER,
            _('The number of virtual cpus.'),
            update_allowed=True
        ),
        MEMORY: properties.Schema(
            properties.Schema.INTEGER,
            _('The container memory size in MiB.'),
            update_allowed=True
        ),
        ENVIRONMENT: properties.Schema(
            properties.Schema.MAP,
            _('The environment variables.'),
        ),
        WORKDIR: properties.Schema(
            properties.Schema.STRING,
            _('The working directory for commands to run in.'),
        ),
        LABELS: properties.Schema(
            properties.Schema.MAP,
            _('Adds a map of labels to a container. '
              'May be used multiple times.'),
        ),
        IMAGE_PULL_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('The policy which determines if the image should '
              'be pulled prior to starting the container.'),
            constraints=[
                constraints.AllowedValues(['ifnotpresent', 'always',
                                           'never']),
            ]
        ),
        RESTART_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('Restart policy to apply when a container exits. Possible '
              'values are "no", "on-failure[:max-retry]", "always", and '
              '"unless-stopped".'),
        ),
        INTERACTIVE: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Keep STDIN open even if not attached.'),
        ),
        IMAGE_DRIVER: properties.Schema(
            properties.Schema.STRING,
            _('The image driver to use to pull container image.'),
            constraints=[
                constraints.AllowedValues(['docker', 'glance']),
            ]
        ),
        HINTS: properties.Schema(
            properties.Schema.MAP,
            _('Arbitrary key-value pairs for scheduler to select host.'),
            support_status=support.SupportStatus(version='10.0.0'),
        ),
        HOSTNAME: properties.Schema(
            properties.Schema.STRING,
            _('The hostname of the container.'),
            support_status=support.SupportStatus(version='10.0.0'),
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('List of security group names or IDs.'),
            support_status=support.SupportStatus(version='10.0.0'),
            default=[]
        ),
        MOUNTS: properties.Schema(
            properties.Schema.LIST,
            _('A list of volumes mounted inside the container.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    VOLUME_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('The ID or name of the cinder volume mount to '
                          'the container.'),
                        constraints=[
                            constraints.CustomConstraint('cinder.volume')
                        ]
                    ),
                    VOLUME_SIZE: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The size of the cinder volume to create.'),
                    ),
                    MOUNT_PATH: properties.Schema(
                        properties.Schema.STRING,
                        _('The filesystem path inside the container.'),
                        required=True,
                    ),
                },
            )
        ),
        NETWORKS: properties.Schema(
            properties.Schema.LIST,
            _('An ordered list of nics to be added to this server, with '
              'information about connected networks, fixed ips, port etc.'),
            support_status=support.SupportStatus(version='11.0.0'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    NETWORK_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('Name or ID of network to create a port on.'),
                        constraints=[
                            constraints.CustomConstraint('neutron.network')
                        ]
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
                          'container.'),
                        constraints=[
                            constraints.CustomConstraint('neutron.port')
                        ]
                    ),
                },
            ),
            update_allowed=True,
        ),
    }

    attributes_schema = {
        NAME: attributes.Schema(
            _('Name of the container.'),
            type=attributes.Schema.STRING
        ),
        ADDRESSES: attributes.Schema(
            _('A dict of all network addresses with corresponding port_id. '
              'Each network will have two keys in dict, they are network '
              'name and network id. '
              'The port ID may be obtained through the following expression: '
              '"{get_attr: [<container>, addresses, <network name_or_id>, 0, '
              'port]}".'),
            type=attributes.Schema.MAP
        ),
    }

    default_client_name = 'zun'

    entity = 'containers'

    def translation_rules(self, props):
        rules = [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.NETWORKS, self.NETWORK_ID],
                client_plugin=self.client_plugin('neutron'),
                finder='find_resourceid_by_name_or_id',
                entity='network'),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.NETWORKS, self.NETWORK_PORT],
                client_plugin=self.client_plugin('neutron'),
                finder='find_resourceid_by_name_or_id',
                entity='port')]
        return rules

    def validate(self):
        super(Container, self).validate()

        policy = self.properties[self.RESTART_POLICY]
        if policy and not self._parse_restart_policy(policy):
            msg = _('restart_policy "%s" is invalid. Valid values are '
                    '"no", "on-failure[:max-retry]", "always", and '
                    '"unless-stopped".') % policy
            raise exception.StackValidationFailed(message=msg)

        mounts = self.properties[self.MOUNTS] or []
        for mount in mounts:
            self._validate_mount(mount)

        networks = self.properties[self.NETWORKS] or []
        for network in networks:
            self._validate_network(network)

    def _validate_mount(self, mount):
        volume_id = mount.get(self.VOLUME_ID)
        volume_size = mount.get(self.VOLUME_SIZE)

        if volume_id is None and volume_size is None:
            msg = _('One of the properties "%(id)s" or "%(size)s" '
                    'should be set for the specified mount of '
                    'container "%(container)s".'
                    '') % dict(id=self.VOLUME_ID,
                               size=self.VOLUME_SIZE,
                               container=self.name)
            raise exception.StackValidationFailed(message=msg)

        # Don't allow specify volume_id and volume_size at the same time
        if volume_id and volume_size:
            raise exception.ResourcePropertyConflict(
                "/".join([self.NETWORKS, self.VOLUME_ID]),
                "/".join([self.NETWORKS, self.VOLUME_SIZE]))

    def _validate_network(self, network):
        net_id = network.get(self.NETWORK_ID)
        port = network.get(self.NETWORK_PORT)
        fixed_ip = network.get(self.NETWORK_FIXED_IP)

        if net_id is None and port is None:
            raise exception.PropertyUnspecifiedError(
                self.NETWORK_ID, self.NETWORK_PORT)

        # Don't allow specify ip and port at the same time
        if fixed_ip and port is not None:
            raise exception.ResourcePropertyConflict(
                ".".join([self.NETWORKS, self.NETWORK_FIXED_IP]),
                ".".join([self.NETWORKS, self.NETWORK_PORT]))

    def handle_create(self):
        args = dict((k, v) for k, v in self.properties.items()
                    if v is not None)
        policy = args.pop(self.RESTART_POLICY, None)
        if policy:
            args[self.RESTART_POLICY] = self._parse_restart_policy(policy)
        mounts = args.pop(self.MOUNTS, None)
        if mounts:
            args[self.MOUNTS] = self._build_mounts(mounts)
        networks = args.pop(self.NETWORKS, None)
        if networks:
            args['nets'] = self._build_nets(networks)
        container = self.client().containers.run(**args)
        self.resource_id_set(container.uuid)
        return container.uuid

    def _parse_restart_policy(self, policy):
        restart_policy = None
        if ":" in policy:
            policy, count = policy.split(":")
            if policy in ['on-failure']:
                restart_policy = {"Name": policy,
                                  "MaximumRetryCount": count or '0'}
        else:
            if policy in ['always', 'unless-stopped', 'on-failure', 'no']:
                restart_policy = {"Name": policy, "MaximumRetryCount": '0'}

        return restart_policy

    def _build_mounts(self, mounts):
        mnts = []
        for mount in mounts:
            mnt_info = {'destination': mount[self.MOUNT_PATH]}
            if mount.get(self.VOLUME_ID):
                mnt_info['source'] = mount[self.VOLUME_ID]
            if mount.get(self.VOLUME_SIZE):
                mnt_info['size'] = mount[self.VOLUME_SIZE]
            mnts.append(mnt_info)
        return mnts

    def _build_nets(self, networks):
        nics = self._build_nics(networks)
        for nic in nics:
            net_id = nic.pop('net-id', None)
            if net_id:
                nic[self.NETWORK_ID] = net_id
            port_id = nic.pop('port-id', None)
            if port_id:
                nic[self.NETWORK_PORT] = port_id

        return nics

    def check_create_complete(self, id):
        container = self.client().containers.get(id)
        if container.status in ('Creating', 'Created'):
            return False
        elif container.status == 'Running':
            return True
        elif container.status == 'Stopped':
            if container.interactive:
                msg = (_("Error in creating container '%(name)s' - "
                         "interactive mode was enabled but the container "
                         "has stopped running") % {'name': self.name})
                raise exception.ResourceInError(
                    status_reason=msg, resource_status=container.status)
            return True
        elif container.status == 'Error':
            msg = (_("Error in creating container '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': container.status_reason})
            raise exception.ResourceInError(status_reason=msg,
                                            resource_status=container.status)
        else:
            msg = (_("Unknown status Container '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': container.status_reason})
            raise exception.ResourceUnknownStatus(status_reason=msg,
                                                  resource_status=container
                                                  .status)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        updaters = []
        container = None

        after_props = json_snippet.properties(self.properties_schema,
                                              self.context)
        if self.NETWORKS in prop_diff:
            prop_diff.pop(self.NETWORKS)
            container = self.client().containers.get(self.resource_id)
            updaters.extend(self._update_networks(container, after_props))

        self.client_plugin().update_container(self.resource_id, **prop_diff)

        return updaters

    def _update_networks(self, container, after_props):
        updaters = []
        new_networks = after_props[self.NETWORKS]
        old_networks = self.properties[self.NETWORKS]
        security_groups = after_props[self.SECURITY_GROUPS]

        interfaces = self.client(version=self.client_plugin().V1_18).\
            containers.network_list(self.resource_id)
        remove_ports, add_nets = self.calculate_networks(
            old_networks, new_networks, interfaces, security_groups)

        for port in remove_ports:
            updaters.append(
                progress.ContainerUpdateProgress(
                    self.resource_id, 'network_detach',
                    handler_extra={'args': (port,)},
                    checker_extra={'args': (port,)})
            )

        for args in add_nets:
            updaters.append(
                progress.ContainerUpdateProgress(
                    self.resource_id, 'network_attach',
                    handler_extra={'kwargs': args},
                    checker_extra={'args': (args['port_id'],)})
            )

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
        return status

    def handle_delete(self):
        if not self.resource_id:
            return
        try:
            self.client().containers.delete(self.resource_id, stop=True)
            return self.resource_id
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)

    def check_delete_complete(self, id):
        if not id:
            return True
        try:
            self.client().containers.get(id)
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)
            return True
        return False

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        try:
            container = self.client().containers.get(self.resource_id)
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)
            return ''

        if name == self.ADDRESSES:
            return self._extend_addresses(container)

        return getattr(container, name, '')

    def _extend_addresses(self, container):
        """Method adds network name to list of addresses.

        This method is used only for resolving attributes.
        """
        nets = self.neutron().list_networks()['networks']
        id_name_mapping_on_network = {net['id']: net['name']
                                      for net in nets}
        addresses = copy.deepcopy(container.addresses)
        for net_uuid in container.addresses or {}:
            addr_list = addresses[net_uuid]
            net_name = id_name_mapping_on_network.get(net_uuid)
            if not net_name:
                continue

            addresses.setdefault(net_name, [])
            addresses[net_name] += addr_list

        return addresses


def resource_mapping():
    return {
        'OS::Zun::Container': Container
    }
