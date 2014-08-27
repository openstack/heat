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

from heat.common import exception
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.vpc import VPC
from heat.openstack.common import excutils
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class ElasticIp(resource.Resource):
    PROPERTIES = (
        DOMAIN, INSTANCE_ID,
    ) = (
        'Domain', 'InstanceId',
    )

    ATTRIBUTES = (
        ALLOCATION_ID,
    ) = (
        'AllocationId',
    )

    properties_schema = {
        DOMAIN: properties.Schema(
            properties.Schema.STRING,
            _('Set to "vpc" to have IP address allocation associated to your '
              'VPC.'),
            constraints=[
                constraints.AllowedValues(['vpc']),
            ]
        ),
        INSTANCE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Instance ID to associate with EIP.')
        ),
    }

    attributes_schema = {
        ALLOCATION_ID: attributes.Schema(
            _('ID that AWS assigns to represent the allocation of the address '
              'for use with Amazon VPC. Returned only for VPC elastic IP '
              'addresses.')
        ),
    }

    def __init__(self, name, json_snippet, stack):
        super(ElasticIp, self).__init__(name, json_snippet, stack)
        self.ipaddress = None

    def _ipaddress(self):
        if self.ipaddress is None and self.resource_id is not None:
            if self.properties[self.DOMAIN]:
                try:
                    ips = self.neutron().show_floatingip(self.resource_id)
                except Exception as ex:
                    self.client_plugin('neutron').ignore_not_found(ex)
                else:
                    self.ipaddress = ips['floatingip']['floating_ip_address']
            else:
                try:
                    ips = self.nova().floating_ips.get(self.resource_id)
                except Exception as e:
                    self.client_plugin('nova').ignore_not_found(e)
                else:
                    self.ipaddress = ips.ip
        return self.ipaddress or ''

    def handle_create(self):
        """Allocate a floating IP for the current tenant."""
        ips = None
        if self.properties[self.DOMAIN]:
            from heat.engine.resources.internet_gateway import InternetGateway

            ext_net = InternetGateway.get_external_network_id(self.neutron())
            props = {'floating_network_id': ext_net}
            ips = self.neutron().create_floatingip({
                'floatingip': props})['floatingip']
            self.ipaddress = ips['floating_ip_address']
            self.resource_id_set(ips['id'])
            LOG.info(_('ElasticIp create %s') % str(ips))
        else:
            try:
                ips = self.nova().floating_ips.create()
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    if self.client_plugin('nova').is_not_found(e):
                        msg = _("No default floating IP pool configured. "
                                "Set 'default_floating_pool' in nova.conf.")
                        LOG.error(msg)

            if ips:
                self.ipaddress = ips.ip
                self.resource_id_set(ips.id)
                LOG.info(_('ElasticIp create %s') % str(ips))

        instance_id = self.properties[self.INSTANCE_ID]
        if instance_id:
            server = self.nova().servers.get(instance_id)
            server.add_floating_ip(self._ipaddress())

    def handle_delete(self):
        instance_id = self.properties[self.INSTANCE_ID]
        if instance_id:
            try:
                server = self.nova().servers.get(instance_id)
                if server:
                    server.remove_floating_ip(self._ipaddress())
            except Exception as e:
                self.client_plugin('nova').ignore_not_found(e)

        """De-allocate a floating IP."""
        if self.resource_id is not None:
            if self.properties[self.DOMAIN]:
                try:
                    self.neutron().delete_floatingip(self.resource_id)
                except Exception as ex:
                    self.client_plugin('neutron').ignore_not_found(ex)
            else:
                try:
                    self.nova().floating_ips.delete(self.resource_id)
                except Exception as e:
                    self.client_plugin('nova').ignore_not_found(e)

    def FnGetRefId(self):
        return unicode(self._ipaddress())

    def _resolve_attribute(self, name):
        if name == self.ALLOCATION_ID:
            return unicode(self.resource_id)


class ElasticIpAssociation(resource.Resource):
    PROPERTIES = (
        INSTANCE_ID, EIP, ALLOCATION_ID, NETWORK_INTERFACE_ID,
    ) = (
        'InstanceId', 'EIP', 'AllocationId', 'NetworkInterfaceId',
    )

    properties_schema = {
        INSTANCE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Instance ID to associate with EIP specified by EIP property.')
        ),
        EIP: properties.Schema(
            properties.Schema.STRING,
            _('EIP address to associate with instance.')
        ),
        ALLOCATION_ID: properties.Schema(
            properties.Schema.STRING,
            _('Allocation ID for VPC EIP address.')
        ),
        NETWORK_INTERFACE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Network interface ID to associate with EIP.')
        ),
    }

    def FnGetRefId(self):
        return self.physical_resource_name_or_FnGetRefId()

    def handle_create(self):
        """Add a floating IP address to a server."""
        if self.properties[self.EIP] is not None \
                and self.properties[self.ALLOCATION_ID] is not None:
                    raise exception.ResourcePropertyConflict(
                        self.EIP,
                        self.ALLOCATION_ID)

        if self.properties[self.EIP]:
            if not self.properties[self.INSTANCE_ID]:
                LOG.debug('Skipping association, InstanceId not specified')
                return
            server = self.nova().servers.get(self.properties[self.INSTANCE_ID])
            server.add_floating_ip(self.properties[self.EIP])
            self.resource_id_set(self.properties[self.EIP])
            LOG.debug('ElasticIpAssociation '
                      '%(instance)s.add_floating_ip(%(eip)s)',
                      {'instance': self.properties[self.INSTANCE_ID],
                       'eip': self.properties[self.EIP]})
        elif self.properties[self.ALLOCATION_ID]:
            port_id = None
            port_rsrc = None
            if self.properties[self.NETWORK_INTERFACE_ID]:
                port_id = self.properties[self.NETWORK_INTERFACE_ID]
                port_rsrc = self.neutron().list_ports(id=port_id)['ports'][0]
            elif self.properties[self.INSTANCE_ID]:
                instance_id = self.properties[self.INSTANCE_ID]
                ports = self.neutron().list_ports(device_id=instance_id)
                port_rsrc = ports['ports'][0]
                port_id = port_rsrc['id']
            else:
                LOG.debug('Skipping association, resource not specified')
                return

            float_id = self.properties[self.ALLOCATION_ID]
            self.resource_id_set(float_id)

            # assuming only one fixed_ip
            subnet_id = port_rsrc['fixed_ips'][0]['subnet_id']
            subnets = self.neutron().list_subnets(id=subnet_id)
            subnet_rsrc = subnets['subnets'][0]
            netid = subnet_rsrc['network_id']

            router = VPC.router_for_vpc(self.neutron(), netid)
            if router is not None:
                floatingip = self.neutron().show_floatingip(float_id)
                floating_net_id = \
                    floatingip['floatingip']['floating_network_id']
                self.neutron().add_gateway_router(
                    router['id'], {'network_id': floating_net_id})

            self.neutron().update_floatingip(
                float_id, {'floatingip': {'port_id': port_id}})

    def handle_delete(self):
        """Remove a floating IP address from a server or port."""
        if self.properties[self.EIP]:
            try:
                instance_id = self.properties[self.INSTANCE_ID]
                server = self.nova().servers.get(instance_id)
                if server:
                    server.remove_floating_ip(self.properties[self.EIP])
            except Exception as e:
                self.client_plugin('nova').ignore_not_found(e)
        elif self.properties[self.ALLOCATION_ID]:
            float_id = self.properties[self.ALLOCATION_ID]
            try:
                self.neutron().update_floatingip(
                    float_id, {'floatingip': {'port_id': None}})
            except Exception as ex:
                self.client_plugin('neutron').ignore_not_found(ex)


def resource_mapping():
    return {
        'AWS::EC2::EIP': ElasticIp,
        'AWS::EC2::EIPAssociation': ElasticIpAssociation,
    }
