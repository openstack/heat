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

import itertools

import eventlet
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import netutils
import tenacity

from heat.common import exception
from heat.common.i18n import _
from heat.engine import resource
from heat.engine.resources.openstack.neutron import port as neutron_port

LOG = logging.getLogger(__name__)


class ServerNetworkMixin(object):

    def _validate_network(self, network):
        net_id = network.get(self.NETWORK_ID)
        port = network.get(self.NETWORK_PORT)
        subnet = network.get(self.NETWORK_SUBNET)
        fixed_ip = network.get(self.NETWORK_FIXED_IP)
        floating_ip = network.get(self.NETWORK_FLOATING_IP)
        str_network = network.get(self.ALLOCATE_NETWORK)

        if (net_id is None and
                port is None and
                subnet is None and
                not str_network):
            msg = _('One of the properties "%(id)s", "%(port_id)s", '
                    '"%(str_network)s" or "%(subnet)s" should be set for the '
                    'specified network of server "%(server)s".'
                    '') % dict(id=self.NETWORK_ID,
                               port_id=self.NETWORK_PORT,
                               subnet=self.NETWORK_SUBNET,
                               str_network=self.ALLOCATE_NETWORK,
                               server=self.name)
            raise exception.StackValidationFailed(message=msg)
        # can not specify str_network with other keys of networks
        # at the same time
        has_value_keys = [k for k, v in network.items() if v is not None]
        if str_network and len(has_value_keys) != 1:
            msg = _('Can not specify "%s" with other keys of networks '
                    'at the same time.') % self.ALLOCATE_NETWORK
            raise exception.StackValidationFailed(message=msg)

        # Nova doesn't allow specify ip and port at the same time
        if fixed_ip and port is not None:
            raise exception.ResourcePropertyConflict(
                "/".join([self.NETWORKS, self.NETWORK_FIXED_IP]),
                "/".join([self.NETWORKS, self.NETWORK_PORT]))

        # if user only specifies network and floating ip, floating ip
        # can't be associated as the the neutron port isn't created/managed
        # by heat
        if floating_ip is not None:
            if net_id is not None and port is None and subnet is None:
                msg = _('Property "%(fip)s" is not supported if only '
                        '"%(net)s" is specified, because the corresponding '
                        'port can not be retrieved.'
                        ) % dict(fip=self.NETWORK_FLOATING_IP,
                                 net=self.NETWORK_ID)
                raise exception.StackValidationFailed(message=msg)

    def _validate_belonging_subnet_to_net(self, network):
        if network.get(self.NETWORK_PORT) is None:
            net = self._get_network_id(network)
            # check if there are subnet and network both specified that
            # subnet belongs to specified network
            subnet = network.get(self.NETWORK_SUBNET)
            if (subnet is not None and net is not None):
                subnet_net = self.client_plugin(
                    'neutron').network_id_from_subnet_id(subnet)
                if subnet_net != net:
                    msg = _('Specified subnet %(subnet)s does not belongs to '
                            'network %(network)s.') % {
                        'subnet': subnet,
                        'network': net}
                    raise exception.StackValidationFailed(message=msg)

    def _create_internal_port(self, net_data, net_number,
                              security_groups=None):
        name = _('%(server)s-port-%(number)s') % {'server': self.name,
                                                  'number': net_number}

        kwargs = self._prepare_internal_port_kwargs(net_data, security_groups)
        kwargs['name'] = name

        port = self.client('neutron').create_port({'port': kwargs})['port']

        # Store ids (used for floating_ip association, updating, etc.)
        # in resource's data.
        self._data_update_ports(port['id'], 'add')

        return port['id']

    def _prepare_internal_port_kwargs(self, net_data, security_groups=None):
        kwargs = {'network_id': self._get_network_id(net_data)}
        fixed_ip = net_data.get(self.NETWORK_FIXED_IP)
        subnet = net_data.get(self.NETWORK_SUBNET)
        body = {}
        if fixed_ip:
            body['ip_address'] = fixed_ip
        if subnet:
            body['subnet_id'] = subnet
        # we should add fixed_ips only if subnet or ip were provided
        if body:
            kwargs.update({'fixed_ips': [body]})

        if security_groups:
            sec_uuids = self.client_plugin(
                'neutron').get_secgroup_uuids(security_groups)
            kwargs['security_groups'] = sec_uuids

        extra_props = net_data.get(self.NETWORK_PORT_EXTRA)
        if extra_props is not None:
            specs = extra_props.pop(neutron_port.Port.VALUE_SPECS)
            if specs:
                kwargs.update(specs)
            port_extra_keys = list(neutron_port.Port.EXTRA_PROPERTIES)
            port_extra_keys.remove(neutron_port.Port.ALLOWED_ADDRESS_PAIRS)
            for key in port_extra_keys:
                if extra_props.get(key) is not None:
                    kwargs[key] = extra_props.get(key)

            allowed_address_pairs = extra_props.get(
                neutron_port.Port.ALLOWED_ADDRESS_PAIRS)
            if allowed_address_pairs is not None:
                for pair in allowed_address_pairs:
                    if (neutron_port.Port.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS
                        in pair and pair.get(
                            neutron_port.Port.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS)
                            is None):
                        del pair[
                            neutron_port.Port.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS]
                port_address_pairs = neutron_port.Port.ALLOWED_ADDRESS_PAIRS
                kwargs[port_address_pairs] = allowed_address_pairs

        return kwargs

    def _delete_internal_port(self, port_id):
        """Delete physical port by id."""
        with self.client_plugin('neutron').ignore_not_found:
            self.client('neutron').delete_port(port_id)

        self._data_update_ports(port_id, 'delete')

    def _delete_internal_ports(self):
        for port_data in self._data_get_ports():
            self._delete_internal_port(port_data['id'])

        self.data_delete('internal_ports')

    def _data_update_ports(self, port_id, action, port_type='internal_ports'):
        data = self._data_get_ports(port_type)

        if action == 'add':
            data.append({'id': port_id})
        elif action == 'delete':
            for port in data:
                if port_id == port['id']:
                    data.remove(port)
                    break

        self.data_set(port_type, jsonutils.dumps(data))

    def _data_get_ports(self, port_type='internal_ports'):
        data = self.data().get(port_type)
        return jsonutils.loads(data) if data else []

    def store_external_ports(self):
        """Store in resource's data IDs of ports created by nova for server.

        If no port property is specified and no internal port has been created,
        nova client takes no port-id and calls port creating into server
        creating. We need to store information about that ports, so store
        their IDs to data with key `external_ports`.
        """
        # check if os-attach-interfaces extension is available on this cloud.
        # If it's not, then novaclient's interface_list method cannot be used
        # to get the list of interfaces.
        if not self.client_plugin().has_extension('os-attach-interfaces'):
            return

        server = self.client().servers.get(self.resource_id)
        ifaces = server.interface_list()
        external_port_ids = set(iface.port_id for iface in ifaces)
        # need to make sure external_ports data doesn't store ids of non-exist
        # ports. Delete such port_id if it's needed.
        data_external_port_ids = set(
            port['id'] for port in self._data_get_ports('external_ports'))
        for port_id in data_external_port_ids - external_port_ids:
            self._data_update_ports(port_id, 'delete',
                                    port_type='external_ports')

        internal_port_ids = set(port['id'] for port in self._data_get_ports())
        # add ids of new external ports which not contains in external_ports
        # data yet. Also, exclude ids of internal ports.
        new_ports = ((external_port_ids - internal_port_ids) -
                     data_external_port_ids)
        for port_id in new_ports:
            self._data_update_ports(port_id, 'add', port_type='external_ports')

    def _build_nics(self, networks, security_groups=None):
        if not networks:
            return None

        str_network = self._str_network(networks)
        if str_network:
            return str_network

        nics = []

        for idx, net in enumerate(networks):
            self._validate_belonging_subnet_to_net(net)
            nic_info = {'net-id': self._get_network_id(net)}
            if net.get(self.NETWORK_PORT):
                nic_info['port-id'] = net[self.NETWORK_PORT]
            elif net.get(self.NETWORK_SUBNET):
                nic_info['port-id'] = self._create_internal_port(
                    net, idx, security_groups)

            # if nic_info including 'port-id', do not set ip for nic
            if not nic_info.get('port-id'):
                if net.get(self.NETWORK_FIXED_IP):
                    ip = net[self.NETWORK_FIXED_IP]
                    if netutils.is_valid_ipv6(ip):
                        nic_info['v6-fixed-ip'] = ip
                    else:
                        nic_info['v4-fixed-ip'] = ip

            if net.get(self.NETWORK_FLOATING_IP) and nic_info.get('port-id'):
                floating_ip_data = {'port_id': nic_info['port-id']}
                if net.get(self.NETWORK_FIXED_IP):
                    floating_ip_data.update(
                        {'fixed_ip_address':
                            net.get(self.NETWORK_FIXED_IP)})
                self._floating_ip_neutron_associate(
                    net.get(self.NETWORK_FLOATING_IP), floating_ip_data)

            if net.get(self.NIC_TAG):
                nic_info[self.NIC_TAG] = net.get(self.NIC_TAG)

            nics.append(nic_info)
        return nics

    def _floating_ip_neutron_associate(self, floating_ip, floating_ip_data):
        self.client('neutron').update_floatingip(
            floating_ip, {'floatingip': floating_ip_data})

    def _floating_ip_disassociate(self, floating_ip):
        with self.client_plugin('neutron').ignore_not_found:
            self.client('neutron').update_floatingip(
                floating_ip, {'floatingip': {'port_id': None}})

    def _find_best_match(self, existing_interfaces, specified_net):
        specified_net_items = set(specified_net.items())
        if specified_net.get(self.NETWORK_PORT) is not None:
            for iface in existing_interfaces:
                if (iface[self.NETWORK_PORT] ==
                        specified_net[self.NETWORK_PORT] and
                        specified_net_items.issubset(set(iface.items()))):
                    return iface
        elif specified_net.get(self.NETWORK_FIXED_IP) is not None:
            for iface in existing_interfaces:
                if (iface[self.NETWORK_FIXED_IP] ==
                        specified_net[self.NETWORK_FIXED_IP] and
                        specified_net_items.issubset(set(iface.items()))):
                    return iface
        else:
            # Best subset intersection
            best, matches, num = None, 0, 0
            for iface in existing_interfaces:
                iface_items = set(iface.items())
                if specified_net_items.issubset(iface_items):
                    num = len(specified_net_items.intersection(iface_items))
                if num > matches:
                    best, matches = iface, num
            return best

    def _exclude_not_updated_networks(self, old_nets, new_nets, interfaces):
        not_updated_nets = []

        # Update old_nets to match interfaces
        self.update_networks_matching_iface_port(old_nets, interfaces)
        # make networks similar by adding None values for not used keys
        for key in self._NETWORK_KEYS:
            # if _net.get(key) is '', convert to None
            for _net in itertools.chain(new_nets, old_nets):
                _net[key] = _net.get(key) or None

        for new_net in list(new_nets):
            new_net_reduced = {k: v for k, v in new_net.items()
                               if k not in self._IFACE_MANAGED_KEYS or
                               v is not None}
            match = self._find_best_match(old_nets, new_net_reduced)
            if match is not None:
                not_updated_nets.append(match)
                new_nets.remove(new_net)
                old_nets.remove(match)

        return not_updated_nets

    def _get_network_id(self, net):
        net_id = net.get(self.NETWORK_ID) or None
        subnet = net.get(self.NETWORK_SUBNET) or None
        if not net_id and subnet:
            net_id = self.client_plugin(
                'neutron').network_id_from_subnet_id(subnet)
        return net_id

    def update_networks_matching_iface_port(self, old_nets, interfaces):

        def get_iface_props(iface):
            ipaddr = None
            subnet = None
            if len(iface.fixed_ips) > 0:
                ipaddr = iface.fixed_ips[0]['ip_address']
                subnet = iface.fixed_ips[0]['subnet_id']
            return {self.NETWORK_PORT: iface.port_id,
                    self.NETWORK_ID: iface.net_id,
                    self.NETWORK_FIXED_IP: ipaddr,
                    self.NETWORK_SUBNET: subnet}

        interfaces_net_props = [get_iface_props(iface) for iface in interfaces]
        for old_net in old_nets:
            if old_net[self.NETWORK_PORT] is None:
                old_net[self.NETWORK_ID] = self._get_network_id(old_net)
            old_net_reduced = {k: v for k, v in old_net.items()
                               if k in self._IFACE_MANAGED_KEYS and
                               v is not None}
            match = self._find_best_match(interfaces_net_props,
                                          old_net_reduced)
            if match is not None:
                old_net.update(match)
                interfaces_net_props.remove(match)

    def _get_available_networks(self):
        # first we get the private networks owned by the tenant
        search_opts = {'tenant_id': self.context.tenant_id, 'shared': False,
                       'admin_state_up': True, }
        nc = self.client('neutron')
        nets = nc.list_networks(**search_opts).get('networks', [])
        # second we get the public shared networks
        search_opts = {'shared': True}
        nets += nc.list_networks(**search_opts).get('networks', [])

        ids = [net['id'] for net in nets]

        return ids

    def _auto_allocate_network(self):
        topology = self.client('neutron').get_auto_allocated_topology(
            self.context.tenant_id)['auto_allocated_topology']

        return topology['id']

    def _calculate_using_str_network(self, ifaces, str_net,
                                     security_groups=None):
        add_nets = []
        remove_ports = [iface.port_id for iface in ifaces or []]
        if str_net == self.NETWORK_AUTO:
            nets = self._get_available_networks()
            if not nets:
                nets = [self._auto_allocate_network()]
            if len(nets) > 1:
                msg = 'Multiple possible networks found.'
                raise exception.UnableToAutoAllocateNetwork(message=msg)
            handle_args = {'port_id': None, 'net_id': nets[0], 'fip': None}
            if security_groups:
                sg_ids = self.client_plugin(
                    'neutron').get_secgroup_uuids(security_groups)
                handle_args['security_groups'] = sg_ids
            add_nets.append(handle_args)
        return remove_ports, add_nets

    def _calculate_using_list_networks(self, old_nets, new_nets, ifaces,
                                       security_groups):
        remove_ports = []
        add_nets = []
        # if update networks between None and empty, no need to
        # detach and attach, the server got first free port already.
        if not new_nets and not old_nets:
            return remove_ports, add_nets

        new_nets = new_nets or []
        old_nets = old_nets or []
        remove_ports, not_updated_nets = self._calculate_remove_ports(
            old_nets, new_nets, ifaces)
        add_nets = self._calculate_add_nets(new_nets, not_updated_nets,
                                            security_groups)

        return remove_ports, add_nets

    def _calculate_remove_ports(self, old_nets, new_nets, ifaces):
        remove_ports = []
        not_updated_nets = []
        # if old nets is empty, it means that the server got first
        # free port. so we should detach this interface.
        if not old_nets:
            for iface in ifaces:
                remove_ports.append(iface.port_id)

        # if we have any information in networks field, we should:
        # 1. find similar networks, if they exist
        # 2. remove these networks from new_nets and old_nets
        #    lists
        # 3. detach unmatched networks, which were present in old_nets
        # 4. attach unmatched networks, which were present in new_nets
        else:
            # if old net is string net, remove the interfaces
            if self._str_network(old_nets):
                remove_ports = [iface.port_id for iface in ifaces or []]
            else:
                # remove not updated networks from old and new networks lists,
                # also get list these networks
                not_updated_nets = self._exclude_not_updated_networks(
                    old_nets, new_nets, ifaces)

                # according to nova interface-detach command detached port
                # will be deleted
                inter_port_data = self._data_get_ports()
                inter_port_ids = [p['id'] for p in inter_port_data]
                for net in old_nets:
                    port_id = net.get(self.NETWORK_PORT)
                    # we can't match the port for some user case, like:
                    # the internal port was detached in nova first, then
                    # user update template to detach this nic. The internal
                    # port will remains till we delete the server resource.
                    if port_id:
                        remove_ports.append(port_id)
                        if port_id in inter_port_ids:
                            # if we have internal port with such id, remove it
                            # instantly.
                            self._delete_internal_port(port_id)
                    if net.get(self.NETWORK_FLOATING_IP):
                        self._floating_ip_disassociate(
                            net.get(self.NETWORK_FLOATING_IP))
        return remove_ports, not_updated_nets

    def _calculate_add_nets(self, new_nets, not_updated_nets,
                            security_groups):
        add_nets = []

        # if new_nets is empty (including the non_updated_nets), we should
        # attach first free port, similar to the behavior for instance
        # creation
        if not new_nets and not not_updated_nets:
            handler_kwargs = {'port_id': None, 'net_id': None, 'fip': None}
            if security_groups:
                sec_uuids = self.client_plugin(
                    'neutron').get_secgroup_uuids(security_groups)
                handler_kwargs['security_groups'] = sec_uuids
            add_nets.append(handler_kwargs)
        else:
            # attach section similar for both variants that
            # were mentioned above
            for idx, net in enumerate(new_nets):
                handler_kwargs = {'port_id': None,
                                  'net_id': None,
                                  'fip': None}

                if net.get(self.NETWORK_PORT):
                    handler_kwargs['port_id'] = net.get(self.NETWORK_PORT)
                elif net.get(self.NETWORK_SUBNET):
                    handler_kwargs['port_id'] = self._create_internal_port(
                        net, idx, security_groups)

                if not handler_kwargs['port_id']:
                    handler_kwargs['net_id'] = self._get_network_id(net)
                    if security_groups:
                        sec_uuids = self.client_plugin(
                            'neutron').get_secgroup_uuids(security_groups)
                        handler_kwargs['security_groups'] = sec_uuids
                if handler_kwargs['net_id']:
                    handler_kwargs['fip'] = net.get('fixed_ip')

                floating_ip = net.get(self.NETWORK_FLOATING_IP)
                if floating_ip:
                    flip_associate = {'port_id': handler_kwargs.get('port_id')}
                    if net.get('fixed_ip'):
                        flip_associate['fixed_ip_address'] = net.get(
                            'fixed_ip')

                    self.update_floating_ip_association(floating_ip,
                                                        flip_associate)

                add_nets.append(handler_kwargs)

        return add_nets

    def _str_network(self, networks):
        # if user specify 'allocate_network', return it
        # otherwise we return None
        for net in networks or []:
            str_net = net.get(self.ALLOCATE_NETWORK)
            if str_net:
                return str_net

    def _is_nic_tagged(self, networks):
        # if user specify 'tag', return True
        # otherwise return False
        for net in networks or []:
            if net.get(self.NIC_TAG):
                return True

        return False

    def calculate_networks(self, old_nets, new_nets, ifaces,
                           security_groups=None):
        new_str_net = self._str_network(new_nets)
        if new_str_net:
            return self._calculate_using_str_network(ifaces, new_str_net,
                                                     security_groups)
        else:
            return self._calculate_using_list_networks(
                old_nets, new_nets, ifaces, security_groups)

    def update_floating_ip_association(self, floating_ip, flip_associate):
        if flip_associate.get('port_id'):
            self._floating_ip_neutron_associate(floating_ip, flip_associate)

    @staticmethod
    def get_all_ports(server):
        return itertools.chain(
            server._data_get_ports(),
            server._data_get_ports('external_ports')
        )

    def detach_ports(self, server):
        existing_server_id = server.resource_id
        for port in self.get_all_ports(server):
            detach_called = self.client_plugin().interface_detach(
                existing_server_id, port['id'])

            if not detach_called:
                return

            try:
                if self.client_plugin().check_interface_detach(
                        existing_server_id, port['id']):
                    LOG.info('Detach interface %(port)s successful from '
                             'server %(server)s.',
                             {'port': port['id'],
                              'server': existing_server_id})
            except tenacity.RetryError:
                raise exception.InterfaceDetachFailed(
                    port=port['id'], server=existing_server_id)

    def attach_ports(self, server):
        prev_server_id = server.resource_id

        for port in self.get_all_ports(server):
            self.client_plugin().interface_attach(prev_server_id,
                                                  port['id'])
            try:
                if self.client_plugin().check_interface_attach(
                        prev_server_id, port['id']):
                    LOG.info('Attach interface %(port)s successful to '
                             'server %(server)s',
                             {'port': port['id'],
                              'server': prev_server_id})
            except tenacity.RetryError:
                raise exception.InterfaceAttachFailed(
                    port=port['id'], server=prev_server_id)

    def prepare_ports_for_replace(self):
        # Check that the interface can be detached
        server = None
        # TODO(TheJulia): Once Story #2002001 is underway,
        # we should be able to replace the query to nova and
        # the check for the failed status with just a check
        # to see if the resource has failed.
        with self.client_plugin().ignore_not_found:
            server = self.client().servers.get(self.resource_id)
        if server and server.status != 'ERROR':
            self.detach_ports(self)
        else:
            # If we are replacing an ERROR'ed node, we need to delete
            # internal ports that we have created, otherwise we can
            # encounter deployment issues with duplicate internal
            # port data attempting to be created in instances being
            # deployed.
            self._delete_internal_ports()

    def restore_ports_after_rollback(self, convergence):
        # In case of convergence, during rollback, the previous rsrc is
        # already selected and is being acted upon.
        if convergence:
            prev_server = self
            rsrc, rsrc_owning_stack, stack = resource.Resource.load(
                prev_server.context, prev_server.replaced_by,
                prev_server.stack.current_traversal, True,
                prev_server.stack.defn._resource_data
            )
            existing_server = rsrc
        else:
            backup_stack = self.stack._backup_stack()
            prev_server = backup_stack.resources.get(self.name)
            existing_server = self

        # Wait until server will move to active state. We can't
        # detach interfaces from server in BUILDING state.
        # In case of convergence, the replacement resource may be
        # created but never have been worked on because the rollback was
        # trigerred or new update was trigerred.
        if existing_server.resource_id is not None:
            try:
                while True:
                    active = self.client_plugin()._check_active(
                        existing_server.resource_id)
                    if active:
                        break
                    eventlet.sleep(1)
            except exception.ResourceInError:
                pass

            self.store_external_ports()
            self.detach_ports(existing_server)

        self.attach_ports(prev_server)
