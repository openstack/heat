# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from heat.engine import clients
from heat.engine import resource
from heat.engine.resources.vpc import VPC
from heat.common import exception

from heat.openstack.common import excutils
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class ElasticIp(resource.Resource):
    properties_schema = {'Domain': {'Type': 'String',
                         'AllowedValues': ['vpc']},
                         'InstanceId': {'Type': 'String'}}
    attributes_schema = {
        "AllocationId": ("ID that AWS assigns to represent the allocation of"
                         "the address for use with Amazon VPC. Returned only"
                         " for VPC elastic IP addresses.")
    }

    def __init__(self, name, json_snippet, stack):
        super(ElasticIp, self).__init__(name, json_snippet, stack)
        self.ipaddress = None

    def _ipaddress(self):
        if self.ipaddress is None and self.resource_id is not None:
            if self.properties['Domain'] and clients.neutronclient:
                ne = clients.neutronclient.exceptions.NeutronClientException
                try:
                    ips = self.neutron().show_floatingip(self.resource_id)
                except ne as e:
                    if e.status_code == 404:
                        logger.warn("Floating IPs not found: %s" % str(e))
                else:
                    self.ipaddress = ips['floatingip']['floating_ip_address']
            else:
                try:
                    ips = self.nova().floating_ips.get(self.resource_id)
                except clients.novaclient.exceptions.NotFound as ex:
                    logger.warn("Floating IPs not found: %s" % str(ex))
                else:
                    self.ipaddress = ips.ip
        return self.ipaddress or ''

    def handle_create(self):
        """Allocate a floating IP for the current tenant."""
        ips = None
        if self.properties['Domain'] and clients.neutronclient:
            from heat.engine.resources.internet_gateway import InternetGateway

            ext_net = InternetGateway.get_external_network_id(self.neutron())
            props = {'floating_network_id': ext_net}
            ips = self.neutron().create_floatingip({
                'floatingip': props})['floatingip']
            self.ipaddress = ips['floating_ip_address']
            self.resource_id_set(ips['id'])
            logger.info('ElasticIp create %s' % str(ips))
        else:
            if self.properties['Domain']:
                raise exception.Error('Domain property can not be set on '
                                      'resource %s without Neutron available' %
                                      self.name)
            try:
                ips = self.nova().floating_ips.create()
            except clients.novaclient.exceptions.NotFound:
                with excutils.save_and_reraise_exception():
                    msg = ("No default floating IP pool configured."
                           "Set 'default_floating_pool' in nova.conf.")
                    logger.error(msg)

            if ips:
                self.ipaddress = ips.ip
                self.resource_id_set(ips.id)
                logger.info('ElasticIp create %s' % str(ips))

        if self.properties['InstanceId']:
            server = self.nova().servers.get(self.properties['InstanceId'])
            res = server.add_floating_ip(self._ipaddress())

    def handle_delete(self):
        if self.properties['InstanceId']:
            try:
                server = self.nova().servers.get(self.properties['InstanceId'])
                if server:
                    server.remove_floating_ip(self._ipaddress())
            except clients.novaclient.exceptions.NotFound as ex:
                pass

        """De-allocate a floating IP."""
        if self.resource_id is not None:
            if self.properties['Domain'] and clients.neutronclient:
                ne = clients.neutronclient.exceptions.NeutronClientException
                try:
                    self.neutron().delete_floatingip(self.resource_id)
                except ne as e:
                    if e.status_code != 404:
                        raise e
            else:
                self.nova().floating_ips.delete(self.resource_id)

    def FnGetRefId(self):
        return unicode(self._ipaddress())

    def _resolve_attribute(self, name):
        if name == 'AllocationId':
            return unicode(self.resource_id)


class ElasticIpAssociation(resource.Resource):
    properties_schema = {'InstanceId': {'Type': 'String',
                                        'Required': False},
                         'EIP': {'Type': 'String'},
                         'AllocationId': {'Type': 'String'},
                         'NetworkInterfaceId': {'Type': 'String'}}

    def FnGetRefId(self):
        return unicode(self.physical_resource_name())

    def handle_create(self):
        """Add a floating IP address to a server."""
        if self.properties['EIP'] is not None \
                and self.properties['AllocationId'] is not None:
                    raise exception.ResourcePropertyConflict('EIP',
                                                             'AllocationId')

        if self.properties['EIP']:
            if not self.properties['InstanceId']:
                logger.warn('Skipping association, InstanceId not specified')
                return
            server = self.nova().servers.get(self.properties['InstanceId'])
            server.add_floating_ip(self.properties['EIP'])
            self.resource_id_set(self.properties['EIP'])
            logger.debug('ElasticIpAssociation %s.add_floating_ip(%s)' %
                         (self.properties['InstanceId'],
                          self.properties['EIP']))
        elif self.properties['AllocationId']:
            assert clients.neutronclient, "Neutron required for VPC operations"
            port_id = None
            port_rsrc = None
            if self.properties['NetworkInterfaceId']:
                port_id = self.properties['NetworkInterfaceId']
                port_rsrc = self.neutron().list_ports(id=port_id)['ports'][0]
            elif self.properties['InstanceId']:
                instance_id = self.properties['InstanceId']
                ports = self.neutron().list_ports(device_id=instance_id)
                port_rsrc = ports['ports'][0]
                port_id = port_rsrc['id']
            else:
                logger.warn('Skipping association, resource not specified')
                return

            float_id = self.properties['AllocationId']
            self.resource_id_set(float_id)

            # assuming only one fixed_ip
            subnet_id = port_rsrc['fixed_ips'][0]['subnet_id']
            subnets = self.neutron().list_subnets(id=subnet_id)
            subnet_rsrc = subnets['subnets'][0]
            netid = subnet_rsrc['network_id']

            router_id = VPC.router_for_vpc(self.neutron(), netid)['id']
            floatingip = self.neutron().show_floatingip(float_id)
            floating_net_id = floatingip['floatingip']['floating_network_id']

            self.neutron().add_gateway_router(
                router_id, {'network_id': floating_net_id})

            self.neutron().update_floatingip(
                float_id, {'floatingip': {'port_id': port_id}})

    def handle_delete(self):
        """Remove a floating IP address from a server or port."""
        if self.properties['EIP']:
            try:
                server = self.nova().servers.get(self.properties['InstanceId'])
                if server:
                    server.remove_floating_ip(self.properties['EIP'])
            except clients.novaclient.exceptions.NotFound as ex:
                pass
        elif self.properties['AllocationId']:
            float_id = self.properties['AllocationId']
            ne = clients.neutronclient.exceptions.NeutronClientException
            try:
                self.neutron().update_floatingip(
                    float_id, {'floatingip': {'port_id': None}})
            except ne as e:
                if e.status_code != 404:
                    raise e


def resource_mapping():
    return {
        'AWS::EC2::EIP': ElasticIp,
        'AWS::EC2::EIPAssociation': ElasticIpAssociation,
    }
