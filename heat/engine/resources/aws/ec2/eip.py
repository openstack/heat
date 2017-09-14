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

from oslo_log import log as logging
import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine.clients import client_exception
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.aws.ec2 import internet_gateway
from heat.engine.resources.aws.ec2 import vpc
from heat.engine import support

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
            support_status=support.SupportStatus(
                status=support.DEPRECATED,
                message=_('Now we only allow vpc here, so no need to set up '
                          'this tag anymore.'),
                version='9.0.0'
            ),
            constraints=[
                constraints.AllowedValues(['vpc']),
            ]
        ),
        INSTANCE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Instance ID to associate with EIP.'),
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('nova.server')
            ]
        ),
    }

    attributes_schema = {
        ALLOCATION_ID: attributes.Schema(
            _('ID that AWS assigns to represent the allocation of the address '
              'for use with Amazon VPC. Returned only for VPC elastic IP '
              'addresses.'),
            type=attributes.Schema.STRING
        ),
    }

    default_client_name = 'nova'

    def __init__(self, name, json_snippet, stack):
        super(ElasticIp, self).__init__(name, json_snippet, stack)
        self.ipaddress = None

    def _ipaddress(self):
        if self.ipaddress is None and self.resource_id is not None:
            try:
                ips = self.neutron().show_floatingip(self.resource_id)
            except Exception as ex:
                self.client_plugin('neutron').ignore_not_found(ex)
            else:
                self.ipaddress = ips['floatingip']['floating_ip_address']
        return self.ipaddress or ''

    def handle_create(self):
        """Allocate a floating IP for the current tenant."""
        ips = None
        ext_net = internet_gateway.InternetGateway.get_external_network_id(
            self.neutron())
        props = {'floating_network_id': ext_net}
        ips = self.neutron().create_floatingip({
            'floatingip': props})['floatingip']
        self.resource_id_set(ips['id'])
        self.ipaddress = ips['floating_ip_address']

        LOG.info('ElasticIp create %s', str(ips))

        instance_id = self.properties[self.INSTANCE_ID]
        if instance_id:
            self.client_plugin().associate_floatingip(instance_id,
                                                      ips['id'])

    def handle_delete(self):
        if self.resource_id is None:
            return
        # may be just create an eip when creation, or create the association
        # failed when creation, there will be no association, if we attempt to
        # disassociate, an exception will raised, we need
        # to catch and ignore it, and then to deallocate the eip
        instance_id = self.properties[self.INSTANCE_ID]
        if instance_id:
            with self.client_plugin().ignore_not_found:
                self.client_plugin().dissociate_floatingip(self.resource_id)
        # deallocate the eip
        with self.client_plugin('neutron').ignore_not_found:
            self.neutron().delete_floatingip(self.resource_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            if self.INSTANCE_ID in prop_diff:
                instance_id = prop_diff[self.INSTANCE_ID]
                if instance_id:
                    self.client_plugin().associate_floatingip(
                        instance_id, self.resource_id)
                else:
                    self.client_plugin().dissociate_floatingip(
                        self.resource_id)

    def get_reference_id(self):
        eip = self._ipaddress()
        if eip:
            return six.text_type(eip)
        else:
            return six.text_type(self.name)

    def _resolve_attribute(self, name):
        if name == self.ALLOCATION_ID:
            return six.text_type(self.resource_id)


class ElasticIpAssociation(resource.Resource):
    PROPERTIES = (
        INSTANCE_ID, EIP, ALLOCATION_ID, NETWORK_INTERFACE_ID,
    ) = (
        'InstanceId', 'EIP', 'AllocationId', 'NetworkInterfaceId',
    )

    properties_schema = {
        INSTANCE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Instance ID to associate with EIP specified by EIP property.'),
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('nova.server')
            ]
        ),
        EIP: properties.Schema(
            properties.Schema.STRING,
            _('EIP address to associate with instance.'),
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('ip_addr')
            ]
        ),
        ALLOCATION_ID: properties.Schema(
            properties.Schema.STRING,
            _('Allocation ID for VPC EIP address.'),
            update_allowed=True
        ),
        NETWORK_INTERFACE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Network interface ID to associate with EIP.'),
            update_allowed=True
        ),
    }

    default_client_name = 'nova'

    def get_reference_id(self):
        return self.physical_resource_name_or_FnGetRefId()

    def validate(self):
        """Validate any of the provided parameters."""
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
            raise exception.PropertyUnspecifiedError('InstanceId',
                                                     'NetworkInterfaceId')

    def _get_port_info(self, ni_id=None, instance_id=None):
        port_id = None
        port_rsrc = None
        if ni_id:
            port_rsrc = self.neutron().list_ports(id=ni_id)['ports'][0]
            port_id = ni_id
        elif instance_id:
            ports = self.neutron().list_ports(device_id=instance_id)
            port_rsrc = ports['ports'][0]
            port_id = port_rsrc['id']

        return port_id, port_rsrc

    def _neutron_add_gateway_router(self, float_id, network_id):
        router = vpc.VPC.router_for_vpc(self.neutron(), network_id)
        if router is not None:
            floatingip = self.neutron().show_floatingip(float_id)
            floating_net_id = floatingip['floatingip']['floating_network_id']
            self.neutron().add_gateway_router(
                router['id'], {'network_id': floating_net_id})

    def _neutron_update_floating_ip(self, allocationId, port_id=None,
                                    ignore_not_found=False):
        try:
            self.neutron().update_floatingip(
                allocationId,
                {'floatingip': {'port_id': port_id}})
        except Exception as e:
            if not (ignore_not_found and self.client_plugin(
                    'neutron').is_not_found(e)):
                raise

    def _remove_floating_ip_address(self, eip, ignore_not_found=False):
        try:
            self.client_plugin().dissociate_floatingip_address(eip)
        except Exception as e:
            addr_not_found = isinstance(
                e, client_exception.EntityMatchNotFound)
            fip_not_found = self.client_plugin().is_not_found(e)
            not_found = addr_not_found or fip_not_found
            if not (ignore_not_found and not_found):
                raise

    def _floatingIp_detach(self):
        eip = self.properties[self.EIP]
        allocation_id = self.properties[self.ALLOCATION_ID]
        if eip:
            # if has eip_old, to remove the eip_old from the instance
            self._remove_floating_ip_address(eip)
        else:
            # if hasn't eip_old, to update neutron floatingIp
            self._neutron_update_floating_ip(allocation_id,
                                             None)

    def _handle_update_eipInfo(self, prop_diff):
        eip_update = prop_diff.get(self.EIP)
        allocation_id_update = prop_diff.get(self.ALLOCATION_ID)
        instance_id = self.properties[self.INSTANCE_ID]
        ni_id = self.properties[self.NETWORK_INTERFACE_ID]
        if eip_update:
            self._floatingIp_detach()
            self.client_plugin().associate_floatingip_address(instance_id,
                                                              eip_update)
            self.resource_id_set(eip_update)
        elif allocation_id_update:
            self._floatingIp_detach()
            port_id, port_rsrc = self._get_port_info(ni_id, instance_id)
            if not port_id or not port_rsrc:
                LOG.error('Port not specified.')
                raise exception.NotFound(_('Failed to update, can not found '
                                           'port info.'))

            network_id = port_rsrc['network_id']
            self._neutron_add_gateway_router(allocation_id_update, network_id)
            self._neutron_update_floating_ip(allocation_id_update, port_id)
            self.resource_id_set(allocation_id_update)

    def _handle_update_portInfo(self, prop_diff):
        instance_id_update = prop_diff.get(self.INSTANCE_ID)
        ni_id_update = prop_diff.get(self.NETWORK_INTERFACE_ID)
        eip = self.properties[self.EIP]
        allocation_id = self.properties[self.ALLOCATION_ID]
        # if update portInfo, no need to detach the port from
        # old instance/floatingip.
        if eip:
            self.client_plugin().associate_floatingip_address(
                instance_id_update, eip)
        else:
            port_id, port_rsrc = self._get_port_info(ni_id_update,
                                                     instance_id_update)
            if not port_id or not port_rsrc:
                LOG.error('Port not specified.')
                raise exception.NotFound(_('Failed to update, can not found '
                                           'port info.'))

            network_id = port_rsrc['network_id']
            self._neutron_add_gateway_router(allocation_id, network_id)
            self._neutron_update_floating_ip(allocation_id, port_id)

    def handle_create(self):
        """Add a floating IP address to a server."""
        eip = self.properties[self.EIP]
        if eip:
            self.client_plugin().associate_floatingip_address(
                self.properties[self.INSTANCE_ID], eip)
            self.resource_id_set(eip)
            LOG.debug('ElasticIpAssociation '
                      '%(instance)s.add_floating_ip(%(eip)s)',
                      {'instance': self.properties[self.INSTANCE_ID],
                       'eip': eip})
        elif self.properties[self.ALLOCATION_ID]:
            ni_id = self.properties[self.NETWORK_INTERFACE_ID]
            instance_id = self.properties[self.INSTANCE_ID]
            port_id, port_rsrc = self._get_port_info(ni_id, instance_id)
            if not port_id or not port_rsrc:
                LOG.warning('Skipping association, resource not specified')
                return

            float_id = self.properties[self.ALLOCATION_ID]
            network_id = port_rsrc['network_id']
            self._neutron_add_gateway_router(float_id, network_id)

            self._neutron_update_floating_ip(float_id, port_id)

            self.resource_id_set(float_id)

    def handle_delete(self):
        """Remove a floating IP address from a server or port."""
        if self.resource_id is None:
            return

        if self.properties[self.EIP]:
            eip = self.properties[self.EIP]
            self._remove_floating_ip_address(eip,
                                             ignore_not_found=True)
        elif self.properties[self.ALLOCATION_ID]:
            float_id = self.properties[self.ALLOCATION_ID]
            self._neutron_update_floating_ip(float_id,
                                             port_id=None,
                                             ignore_not_found=True)

    def needs_replace_with_prop_diff(self, changed_properties_set,
                                     after_props, before_props):
        if (self.ALLOCATION_ID in changed_properties_set or
                self.EIP in changed_properties_set):
            instance_id, ni_id = None, None
            if self.INSTANCE_ID in changed_properties_set:
                instance_id = after_props.get(self.INSTANCE_ID)
            if self.NETWORK_INTERFACE_ID in changed_properties_set:
                ni_id = after_props.get(self.NETWORK_INTERFACE_ID)
            return bool(instance_id or ni_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            if self.ALLOCATION_ID in prop_diff or self.EIP in prop_diff:
                self._handle_update_eipInfo(prop_diff)
            elif (self.INSTANCE_ID in prop_diff or
                  self.NETWORK_INTERFACE_ID in prop_diff):
                self._handle_update_portInfo(prop_diff)


def resource_mapping():
    return {
        'AWS::EC2::EIP': ElasticIp,
        'AWS::EC2::EIPAssociation': ElasticIpAssociation,
    }
