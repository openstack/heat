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

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LI
from heat.engine.cfn import functions as cfn_funcs

LOG = logging.getLogger(__name__)


class ServerNetworkMixin(object):

    def _validate_network(self, network):
        net_uuid = network.get(self.NETWORK_UUID)
        net_id = network.get(self.NETWORK_ID)
        port = network.get(self.NETWORK_PORT)
        subnet = network.get(self.NETWORK_SUBNET)

        if (net_id is None and port is None
           and net_uuid is None and subnet is None):
            msg = _('One of the properties "%(id)s", "%(port_id)s", '
                    '"%(uuid)s" or "%(subnet)s" should be set for the '
                    'specified network of server "%(server)s".'
                    '') % dict(id=self.NETWORK_ID,
                               port_id=self.NETWORK_PORT,
                               uuid=self.NETWORK_UUID,
                               subnet=self.NETWORK_SUBNET,
                               server=self.name)
            raise exception.StackValidationFailed(message=msg)

        if net_uuid and net_id:
            msg = _('Properties "%(uuid)s" and "%(id)s" are both set '
                    'to the network "%(network)s" for the server '
                    '"%(server)s". The "%(uuid)s" property is deprecated. '
                    'Use only "%(id)s" property.'
                    '') % dict(uuid=self.NETWORK_UUID,
                               id=self.NETWORK_ID,
                               network=network[self.NETWORK_ID],
                               server=self.name)
            raise exception.StackValidationFailed(message=msg)
        elif net_uuid:
            LOG.info(_LI('For the server "%(server)s" the "%(uuid)s" '
                         'property is set to network "%(network)s". '
                         '"%(uuid)s" property is deprecated. Use '
                         '"%(id)s"  property instead.'),
                     dict(uuid=self.NETWORK_UUID,
                          id=self.NETWORK_ID,
                          network=network[self.NETWORK_ID],
                          server=self.name))

        # If subnet and net are specified with some external resources, check
        # them. Otherwise, if their are resources of current stack, skip
        # validating in case of raising error and check it only during
        # resource creating.
        is_ref = False
        for item in [subnet, net_uuid, net_id]:
            if isinstance(item, (cfn_funcs.ResourceRef, cfn_funcs.GetAtt)):
                is_ref = True
                break
        if not is_ref:
            self._validate_belonging_subnet_to_net(network)

    def _validate_belonging_subnet_to_net(self, network):
        if network.get(self.NETWORK_PORT) is None and self.is_using_neutron():
            net = self._get_network_id(network)
            # check if there are subnet and network both specified that
            # subnet belongs to specified network
            if (network.get(self.NETWORK_SUBNET) is not None
               and (net is not None)):
                subnet_net = self.client_plugin(
                    'neutron').network_id_from_subnet_id(
                    self._get_subnet_id(network))
                if subnet_net != net:
                    msg = _('Specified subnet %(subnet)s does not belongs to'
                            'network %(network)s.') % {
                        'subnet': subnet_net,
                        'network': net}
                    raise exception.StackValidationFailed(message=msg)

    def _create_internal_port(self, net_data, net_number):
        name = _('%(server)s-port-%(number)s') % {'server': self.name,
                                                  'number': net_number}

        kwargs = {'network_id': self._get_network_id(net_data),
                  'name': name}
        fixed_ip = net_data.get(self.NETWORK_FIXED_IP)
        subnet = net_data.get(self.NETWORK_SUBNET)
        body = {}
        if fixed_ip:
            body['ip_address'] = fixed_ip
        if subnet:
            body['subnet_id'] = self._get_subnet_id(net_data)
        # we should add fixed_ips only if subnet or ip were provided
        if body:
            kwargs.update({'fixed_ips': [body]})

        port = self.client('neutron').create_port({'port': kwargs})['port']

        # Store ids (used for floating_ip association, updating, etc.)
        # in resource's data.
        self._data_update_ports(port['id'], 'add')

        return port['id']

    def _delete_internal_port(self, port_id):
        """Delete physical port by id."""
        try:
            self.client('neutron').delete_port(port_id)
        except Exception as ex:
            self.client_plugin('neutron').ignore_not_found(ex)

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

        # check if OSInterface extension is installed on this cloud. If it's
        # not, then novaclient's interface_list method cannot be used to get
        # the list of interfaces.
        if not self.client_plugin()._has_extension(
                self.client_plugin().OS_INTERFACE_EXTENSION):
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

    def _build_nics(self, networks):
        if not networks:
            return None

        nics = []

        for idx, net in enumerate(networks):
            self._validate_belonging_subnet_to_net(net)
            nic_info = {'net-id': self._get_network_id(net)}
            if net.get(self.NETWORK_FIXED_IP):
                ip = net[self.NETWORK_FIXED_IP]
                if netutils.is_valid_ipv6(ip):
                    nic_info['v6-fixed-ip'] = ip
                else:
                    nic_info['v4-fixed-ip'] = ip
            if net.get(self.NETWORK_PORT):
                nic_info['port-id'] = net[self.NETWORK_PORT]
            elif self.is_using_neutron() and net.get(self.NETWORK_SUBNET):
                nic_info['port-id'] = self._create_internal_port(net, idx)
            nics.append(nic_info)
        return nics

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
        # network and network_id properties can be used interchangeably
        # if move the same value from one properties to another, it should
        # not change anything, i.e. it will be the same port/interface
        net_id = (net.get(self.NETWORK_UUID) or
                  net.get(self.NETWORK_ID) or None)

        if net_id:
            if self.is_using_neutron():
                net_id = self.client_plugin(
                    'neutron').resolve_network(
                    net, self.NETWORK_ID, self.NETWORK_UUID)
            else:
                net_id = self.client_plugin(
                    'nova').get_nova_network_id(net_id)
        elif net.get(self.NETWORK_SUBNET):
            net_id = self.client_plugin('neutron').network_id_from_subnet_id(
                self._get_subnet_id(net))
        return net_id

    def _get_subnet_id(self, net):
        return self.client_plugin('neutron').find_neutron_resource(
            net, self.NETWORK_SUBNET, 'subnet')

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

        handler_kwargs = {'port_id': None, 'net_id': None, 'fip': None}
        # if new_nets is None, we should attach first free port,
        # according to similar behavior during instance creation
        if attach_first_free_port:
            add_nets.append(handler_kwargs)
        # attach section similar for both variants that
        # were mentioned above
        for idx, net in enumerate(new_nets):
            handler_kwargs = {'port_id': None,
                              'net_id': self._get_network_id(net),
                              'fip': None}
            if handler_kwargs['net_id']:
                handler_kwargs['fip'] = net.get('fixed_ip')
            if net.get(self.NETWORK_PORT):
                handler_kwargs['port_id'] = net.get(self.NETWORK_PORT)
            elif self.is_using_neutron() and net.get(self.NETWORK_SUBNET):
                handler_kwargs['port_id'] = self._create_internal_port(net,
                                                                       idx)

            add_nets.append(handler_kwargs)

        return remove_ports, add_nets

    def prepare_ports_for_replace(self):
        if not self.is_using_neutron():
            return

        data = {'external_ports': [],
                'internal_ports': []}
        port_data = itertools.chain(
            [('internal_ports', port) for port in self._data_get_ports()],
            [('external_ports', port)
             for port in self._data_get_ports('external_ports')])
        for port_type, port in port_data:
            # store port fixed_ips for restoring after failed update
            port_details = self.client('neutron').show_port(port['id'])['port']
            fixed_ips = port_details.get('fixed_ips', [])
            data[port_type].append({'id': port['id'], 'fixed_ips': fixed_ips})

        if data.get('internal_ports'):
            self.data_set('internal_ports',
                          jsonutils.dumps(data['internal_ports']))
        if data.get('external_ports'):
            self.data_set('external_ports',
                          jsonutils.dumps(data['external_ports']))
        # reset fixed_ips for these ports by setting for each of them
        # fixed_ips to []
        for port_type, port in port_data:
            self.client('neutron').update_port(
                port['id'], {'port': {'fixed_ips': []}})

    def restore_ports_after_rollback(self):
        if not self.is_using_neutron():
            return

        old_server = self.stack._backup_stack().resources.get(self.name)

        port_data = itertools.chain(self._data_get_ports(),
                                    self._data_get_ports('external_ports'))
        for port in port_data:
            self.client('neutron').update_port(port['id'],
                                               {'port': {'fixed_ips': []}})

        old_port_data = itertools.chain(
            old_server._data_get_ports(),
            old_server._data_get_ports('external_ports'))
        for port in old_port_data:
            fixed_ips = port['fixed_ips']
            self.client('neutron').update_port(
                port['id'], {'port': {'fixed_ips': fixed_ips}})
