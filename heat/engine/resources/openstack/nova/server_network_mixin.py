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

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import netutils
import retrying

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LI

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

        if net_id is None and port is None and subnet is None:
            msg = _('One of the properties "%(id)s", "%(port_id)s" '
                    'or "%(subnet)s" should be set for the '
                    'specified network of server "%(server)s".'
                    '') % dict(id=self.NETWORK_ID,
                               port_id=self.NETWORK_PORT,
                               subnet=self.NETWORK_SUBNET,
                               server=self.name)
            raise exception.StackValidationFailed(message=msg)

        if port is not None and not self.is_using_neutron():
            msg = _('Property "%s" is supported only for '
                    'Neutron.') % self.NETWORK_PORT
            raise exception.StackValidationFailed(message=msg)

        # Nova doesn't allow specify ip and port at the same time
        if fixed_ip and port is not None:
            raise exception.ResourcePropertyConflict(
                "/".join([self.NETWORKS, self.NETWORK_FIXED_IP]),
                "/".join([self.NETWORKS, self.NETWORK_PORT]))

        # if user only specifies network and floating ip, floating ip
        # can't be associated as the the neutron port isn't created/managed
        # by heat
        if floating_ip is not None and self.is_using_neutron():
            if net_id is not None and port is None and subnet is None:
                msg = _('Property "%(fip)s" is not supported if only '
                        '"%(net)s" is specified, because the corresponding '
                        'port can not be retrieved.'
                        ) % dict(fip=self.NETWORK_FLOATING_IP,
                                 net=self.NETWORK_ID)
                raise exception.StackValidationFailed(message=msg)

    def _validate_belonging_subnet_to_net(self, network):
        if network.get(self.NETWORK_PORT) is None and self.is_using_neutron():
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
        if not self.is_using_neutron():
            return

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
        nics = []

        for idx, net in enumerate(networks):
            self._validate_belonging_subnet_to_net(net)
            nic_info = {'net-id': self._get_network_id(net)}
            if net.get(self.NETWORK_PORT):
                nic_info['port-id'] = net[self.NETWORK_PORT]
            elif self.is_using_neutron() and net.get(self.NETWORK_SUBNET):
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

            nics.append(nic_info)
        return nics

    def _floating_ip_neutron_associate(self, floating_ip, floating_ip_data):
        if self.is_using_neutron():
            self.client('neutron').update_floatingip(
                floating_ip, {'floatingip': floating_ip_data})

    def _floating_ip_nova_associate(self, floating_ip):
        fl_ip = self.client().floating_ips.get(floating_ip)
        if fl_ip and self.resource_id:
            self.client().servers.add_floating_ip(self.resource_id, fl_ip.ip)

    def _floating_ips_disassociate(self):
        networks = self.properties[self.NETWORKS] or []
        for network in networks:
            floating_ip = network.get(self.NETWORK_FLOATING_IP)
            if floating_ip is not None:
                self._floating_ip_disassociate(floating_ip)

    def _floating_ip_disassociate(self, floating_ip):
        if self.is_using_neutron():
            with self.client_plugin('neutron').ignore_not_found:
                self.client('neutron').update_floatingip(
                    floating_ip, {'floatingip': {'port_id': None}})
        else:
            with self.client_plugin().ignore_conflict_and_not_found:
                fl_ip = self.client().floating_ips.get(floating_ip)
                self.client().servers.remove_floating_ip(self.resource_id,
                                                         fl_ip.ip)

    def _exclude_not_updated_networks(self, old_nets, new_nets):
        # make networks similar by adding None vlues for not used keys
        for key in self._NETWORK_KEYS:
            # if _net.get(key) is '', convert to None
            for _net in itertools.chain(new_nets, old_nets):
                _net[key] = _net.get(key) or None
        # find matches and remove them from old and new networks
        not_updated_nets = [net for net in old_nets if net in new_nets]
        for net in not_updated_nets:
            old_nets.remove(net)
            new_nets.remove(net)
        return not_updated_nets

    def _get_network_id(self, net):
        net_id = net.get(self.NETWORK_ID) or None
        subnet = net.get(self.NETWORK_SUBNET) or None
        if not net_id and subnet:
            net_id = self.client_plugin(
                'neutron').network_id_from_subnet_id(subnet)
        return net_id

    def update_networks_matching_iface_port(self, nets, interfaces):

        def find_equal(port, net_id, ip, nets):
            for net in nets:
                if (net.get('port') == port or
                        (net.get('fixed_ip') == ip and
                         self._get_network_id(net) == net_id)):
                    return net

        def find_poor_net(net_id, nets):
            for net in nets:
                if (not net.get('port') and not net.get('fixed_ip') and
                        self._get_network_id(net) == net_id):
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

    def calculate_networks(self, old_nets, new_nets, ifaces,
                           security_groups=None):
        remove_ports = []
        add_nets = []
        attach_first_free_port = False
        if not new_nets:
            new_nets = []
            attach_first_free_port = True

        # if old nets is None, it means that the server got first
        # free port. so we should detach this interface.
        if old_nets is None:
            for iface in ifaces:
                remove_ports.append(iface.port_id)

        # if we have any information in networks field, we should:
        # 1. find similar networks, if they exist
        # 2. remove these networks from new_nets and old_nets
        #    lists
        # 3. detach unmatched networks, which were present in old_nets
        # 4. attach unmatched networks, which were present in new_nets
        else:
            # remove not updated networks from old and new networks lists,
            # also get list these networks
            not_updated_nets = self._exclude_not_updated_networks(old_nets,
                                                                  new_nets)

            self.update_networks_matching_iface_port(
                old_nets + not_updated_nets, ifaces)

            # according to nova interface-detach command detached port
            # will be deleted
            for net in old_nets:
                if net.get(self.NETWORK_PORT):
                    remove_ports.append(net.get(self.NETWORK_PORT))
                    if self.data().get('internal_ports'):
                        # if we have internal port with such id, remove it
                        # instantly.
                        self._delete_internal_port(net.get(self.NETWORK_PORT))
                if net.get(self.NETWORK_FLOATING_IP):
                    self._floating_ip_disassociate(
                        net.get(self.NETWORK_FLOATING_IP))

        handler_kwargs = {'port_id': None, 'net_id': None, 'fip': None}
        # if new_nets is None, we should attach first free port,
        # according to similar behavior during instance creation
        if attach_first_free_port:
            add_nets.append(handler_kwargs)
        # attach section similar for both variants that
        # were mentioned above
        for idx, net in enumerate(new_nets):
            handler_kwargs = {'port_id': None,
                              'net_id': None,
                              'fip': None}

            if net.get(self.NETWORK_PORT):
                handler_kwargs['port_id'] = net.get(self.NETWORK_PORT)
            elif self.is_using_neutron() and net.get(self.NETWORK_SUBNET):
                handler_kwargs['port_id'] = self._create_internal_port(
                    net, idx, security_groups)

            if not handler_kwargs['port_id']:
                handler_kwargs['net_id'] = self._get_network_id(net)
            if handler_kwargs['net_id']:
                handler_kwargs['fip'] = net.get('fixed_ip')

            floating_ip = net.get(self.NETWORK_FLOATING_IP)
            if floating_ip:
                flip_associate = {'port_id': handler_kwargs.get('port_id')}
                if net.get('fixed_ip'):
                    flip_associate['fixed_ip_address'] = net.get('fixed_ip')

                self.update_floating_ip_association(floating_ip,
                                                    flip_associate)

            add_nets.append(handler_kwargs)

        return remove_ports, add_nets

    def update_floating_ip_association(self, floating_ip, flip_associate):
        if self.is_using_neutron() and flip_associate.get('port_id'):
            self._floating_ip_neutron_associate(floating_ip, flip_associate)
        elif not self.is_using_neutron():
            self._floating_ip_nova_associate(floating_ip)

    def prepare_ports_for_replace(self):
        if not self.is_using_neutron():
            return

        data = {'external_ports': [],
                'internal_ports': []}
        port_data = list(itertools.chain(
            [('internal_ports', port) for port in self._data_get_ports()],
            [('external_ports', port)
             for port in self._data_get_ports('external_ports')]))
        for port_type, port in port_data:
            data[port_type].append({'id': port['id']})

        # detach the ports from the server
        server_id = self.resource_id
        for port_type, port in port_data:
            self.client_plugin().interface_detach(server_id, port['id'])
            try:
                if self.client_plugin().check_interface_detach(
                        server_id, port['id']):
                    LOG.info(_LI('Detach interface %(port)s successful '
                                 'from server %(server)s when prepare '
                                 'for replace.')
                             % {'port': port['id'],
                                'server': server_id})
            except retrying.RetryError:
                raise exception.InterfaceDetachFailed(
                    port=port['id'], server=server_id)

    def restore_ports_after_rollback(self, convergence):
        if not self.is_using_neutron():
            return

        # In case of convergence, during rollback, the previous rsrc is
        # already selected and is being acted upon.
        backup_res = self.stack._backup_stack().resources.get(self.name)
        prev_server = self if convergence else backup_res

        if convergence:
            rsrc, rsrc_owning_stack, stack = resource.Resource.load(
                prev_server.context, prev_server.replaced_by, True,
                prev_server.stack.cache_data
            )
            existing_server = rsrc
        else:
            existing_server = self

        port_data = itertools.chain(
            existing_server._data_get_ports(),
            existing_server._data_get_ports('external_ports')
        )

        existing_server_id = existing_server.resource_id
        for port in port_data:
            # detach the ports from current resource
            self.client_plugin().interface_detach(
                existing_server_id, port['id'])
            try:
                if self.client_plugin().check_interface_detach(
                        existing_server_id, port['id']):
                    LOG.info(_LI('Detach interface %(port)s successful from '
                                 'server %(server)s when restore after '
                                 'rollback.')
                             % {'port': port['id'],
                                'server': existing_server_id})
            except retrying.RetryError:
                raise exception.InterfaceDetachFailed(
                    port=port['id'], server=existing_server_id)

        # attach the ports for old resource
        prev_port_data = itertools.chain(
            prev_server._data_get_ports(),
            prev_server._data_get_ports('external_ports'))

        prev_server_id = prev_server.resource_id

        for port in prev_port_data:
            self.client_plugin().interface_attach(prev_server_id,
                                                  port['id'])
            try:
                if self.client_plugin().check_interface_attach(
                        prev_server_id, port['id']):
                    LOG.info(_LI('Attach interface %(port)s successful to '
                                 'server %(server)s when restore after '
                                 'rollback.')
                             % {'port': port['id'],
                                'server': prev_server_id})
            except retrying.RetryError:
                raise exception.InterfaceAttachFailed(
                    port=port['id'], server=prev_server_id)
