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
            _('Instance ID to associate with EIP.'),
            update_allowed=True
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
        if self.resource_id is None:
            return
        # may be just create an eip when creation, or create the association
        # failed when creation, there will no association, if we attempt to
        # disassociate, an exception will raised, we need
        # to catch and ignore it, and then to deallocate the eip
        instance_id = self.properties[self.INSTANCE_ID]
        if instance_id:
            try:
                server = self.nova().servers.get(instance_id)
                if server:
                    server.remove_floating_ip(self._ipaddress())
            except Exception as e:
                is_not_found = self.client_plugin('nova').is_not_found(e)
                is_unprocessable_entity = self.client_plugin('nova').\
                    is_unprocessable_entity(e)

                if (not is_not_found and not is_unprocessable_entity):
                    raise

        # deallocate the eip
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

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            if self.INSTANCE_ID in prop_diff:
                instance_id = prop_diff.get(self.INSTANCE_ID)
                if instance_id:
                    # no need to remove the floating ip from the old instance,
                    # nova does this automatically when calling
                    # add_floating_ip().
                    server = self.nova().servers.get(instance_id)
                    server.add_floating_ip(self._ipaddress())
                else:
                    # to remove the floating_ip from the old instance
                    instance_id_old = self.properties[self.INSTANCE_ID]
                    if instance_id_old:
                        server = self.nova().servers.get(instance_id_old)
                        server.remove_floating_ip(self._ipaddress())

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

    def validate(self):
        '''
        Validate any of the provided parameters
        '''
        super(ElasticIpAssociation, self).validate()
        eip = self.properties[self.EIP]
        allocation_id = self.properties[self.ALLOCATION_ID]
        instance_id = self.properties[self.INSTANCE_ID]
        ni_id = self.properties[self.NETWORK_INTERFACE_ID]
        # to check EIP and ALLOCATION_ID, should provide one of
        if bool(eip) == bool(allocation_id):
            msg = _("Either 'EIP' or 'AllocationId' must be provided.")
            raise exception.StackValidationFailed(message=msg)
        # to check if has EIP, also should specify InstanceId
        if eip and not instance_id:
            msg = _("Must specify 'InstanceId' if you specify 'EIP'.")
            raise exception.StackValidationFailed(message=msg)
        # to check InstanceId and NetworkInterfaceId, should provide
        # at least one
        if not instance_id and not ni_id:
            msg = _("Must specify at least one of 'InstanceId' "
                    "or 'NetworkInterfaceId'.")
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        """Add a floating IP address to a server."""
        if self.properties[self.EIP]:
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

            network_id = port_rsrc['network_id']
            router = VPC.router_for_vpc(self.neutron(), network_id)
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
