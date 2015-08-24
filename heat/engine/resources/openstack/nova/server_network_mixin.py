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

from oslo_utils import netutils


class ServerNetworkMixin(object):
    def _build_nics(self, networks):
        if not networks:
            return None

        nics = []

        for net_data in networks:
            nic_info = {}
            net_identifier = (net_data.get(self.NETWORK_UUID) or
                              net_data.get(self.NETWORK_ID))
            if net_identifier:
                if self.is_using_neutron():
                    net_id = (self.client_plugin(
                        'neutron').resolve_network(
                        net_data, self.NETWORK_ID, self.NETWORK_UUID))
                else:
                    net_id = (self.client_plugin(
                        'nova').get_nova_network_id(net_identifier))
                nic_info['net-id'] = net_id
            if net_data.get(self.NETWORK_FIXED_IP):
                ip = net_data[self.NETWORK_FIXED_IP]
                if netutils.is_valid_ipv6(ip):
                    nic_info['v6-fixed-ip'] = ip
                else:
                    nic_info['v4-fixed-ip'] = ip
            if net_data.get(self.NETWORK_PORT):
                nic_info['port-id'] = net_data[self.NETWORK_PORT]
            nics.append(nic_info)
        return nics

    def _get_network_matches(self, old_networks, new_networks):
        # make new_networks similar on old_networks
        for new_net in new_networks:
            for key in ('port', 'network', 'fixed_ip', 'uuid'):
                # if new_net.get(key) is '', convert to None
                if not new_net.get(key):
                    new_net[key] = None
        for old_net in old_networks:
            for key in ('port', 'network', 'fixed_ip', 'uuid'):
                # if old_net.get(key) is '', convert to None
                if not old_net.get(key):
                    old_net[key] = None
        # find matches and remove them from old and new networks
        not_updated_networks = []
        for net in old_networks:
            if net in new_networks:
                new_networks.remove(net)
                not_updated_networks.append(net)
        for net in not_updated_networks:
            old_networks.remove(net)
        return not_updated_networks

    def _get_network_id(self, net):
        net_id = None
        if net.get(self.NETWORK_ID):
            if self.is_using_neutron():
                net_id = self.client_plugin(
                    'neutron').resolve_network(
                    net,
                    self.NETWORK_ID, self.NETWORK_UUID)
            else:
                net_id = self.client_plugin(
                    'nova').get_nova_network_id(net.get(self.NETWORK_ID))
        return net_id

    def update_networks_matching_iface_port(self, nets, interfaces):

        def find_equal(port, net_id, ip, nets):
            for net in nets:

                if (net.get('port') == port or
                        (net.get('fixed_ip') == ip and
                         (self._get_network_id(net) == net_id or
                          net.get('uuid') == net_id))):
                    return net

        def find_poor_net(net_id, nets):
            for net in nets:
                if (not net.get('port') and not net.get('fixed_ip') and
                        (self._get_network_id(net) == net_id or
                         net.get('uuid') == net_id)):
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

    def calculate_networks(self, old_nets, new_nets, ifaces):
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
            not_updated_nets = self._get_network_matches(old_nets, new_nets)

            self.update_networks_matching_iface_port(
                old_nets + not_updated_nets, ifaces)

            # according to nova interface-detach command detached port
            # will be deleted
            for net in old_nets:
                if net.get(self.NETWORK_PORT):
                    remove_ports.append(net.get(self.NETWORK_PORT))
        handler_kwargs = {'port_id': None, 'net_id': None, 'fip': None}
        # if new_nets is None, we should attach first free port,
        # according to similar behavior during instance creation
        if attach_first_free_port:
            add_nets.append(handler_kwargs)
        # attach section similar for both variants that
        # were mentioned above
        for net in new_nets:
            if net.get(self.NETWORK_PORT):
                handler_kwargs['port_id'] = net.get(self.NETWORK_PORT)
            elif net.get(self.NETWORK_ID):
                handler_kwargs['net_id'] = self._get_network_id(net)
                handler_kwargs['fip'] = net.get('fixed_ip')
            elif net.get(self.NETWORK_UUID):
                handler_kwargs['net_id'] = net['uuid']
                handler_kwargs['fip'] = net.get('fixed_ip')

            add_nets.append(handler_kwargs)

        return remove_ports, add_nets
