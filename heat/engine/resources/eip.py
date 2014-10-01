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

from oslo.utils import excutils

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.vpc import VPC
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
            _('Instance ID to associate with EIP specified by EIP property.'),
            update_allowed=True
        ),
        EIP: properties.Schema(
            properties.Schema.STRING,
            _('EIP address to associate with instance.'),
            update_allowed=True
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
        router = VPC.router_for_vpc(self.neutron(), network_id)
        if router is not None:
            floatingip = self.neutron().show_floatingip(float_id)
            floating_net_id = \
                floatingip['floatingip']['floating_network_id']
            self.neutron().add_gateway_router(
                router['id'], {'network_id': floating_net_id})

    def _neutron_update_floating_ip(self, allocationId, port_id=None,
                                    ignore_not_found=False):
        try:
            self.neutron().update_floatingip(
                allocationId,
                {'floatingip': {'port_id': port_id}})
        except Exception as e:
            if ignore_not_found:
                self.client_plugin('neutron').ignore_not_found(e)
            else:
                raise

    def _nova_remove_floating_ip(self, instance_id, eip,
                                 ignore_not_found=False):
        server = None
        try:
            server = self.nova().servers.get(instance_id)
            server.remove_floating_ip(eip)
        except Exception as e:
            is_not_found = self.client_plugin('nova').is_not_found(e)
            iue = self.client_plugin('nova').is_unprocessable_entity(e)
            if ((not ignore_not_found and is_not_found) or
                    (not is_not_found and not iue)):
                raise

        return server

    def _floatingIp_detach(self,
                           nova_ignore_not_found=False,
                           neutron_ignore_not_found=False):
        eip = self.properties[self.EIP]
        allocation_id = self.properties[self.ALLOCATION_ID]
        instance_id = self.properties[self.INSTANCE_ID]
        server = None
        if eip:
            # if has eip_old, to remove the eip_old from the instance
            server = self._nova_remove_floating_ip(instance_id,
                                                   eip,
                                                   nova_ignore_not_found)
        else:
            # if hasn't eip_old, to update neutron floatingIp
            self._neutron_update_floating_ip(allocation_id,
                                             None,
                                             neutron_ignore_not_found)

        return server

    def _handle_update_eipInfo(self, prop_diff):
        eip_update = prop_diff.get(self.EIP)
        allocation_id_update = prop_diff.get(self.ALLOCATION_ID)
        instance_id = self.properties[self.INSTANCE_ID]
        ni_id = self.properties[self.NETWORK_INTERFACE_ID]
        if eip_update:
            server = self._floatingIp_detach(neutron_ignore_not_found=True)
            if server:
                # then to attach the eip_update to the instance
                server.add_floating_ip(eip_update)
                self.resource_id_set(eip_update)
        elif allocation_id_update:
            self._floatingIp_detach(nova_ignore_not_found=True)
            port_id, port_rsrc = self._get_port_info(ni_id, instance_id)
            if not port_id or not port_rsrc:
                LOG.error(_('Port not specified.'))
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
            server = self.nova().servers.get(instance_id_update)
            server.add_floating_ip(eip)
        else:
            port_id, port_rsrc = self._get_port_info(ni_id_update,
                                                     instance_id_update)
            if not port_id or not port_rsrc:
                LOG.error(_('Port not specified.'))
                raise exception.NotFound(_('Failed to update, can not found '
                                           'port info.'))

            network_id = port_rsrc['network_id']
            self._neutron_add_gateway_router(allocation_id, network_id)
            self._neutron_update_floating_ip(allocation_id, port_id)

    def _validate_update_properties(self, prop_diff):
        # according to aws doc, when update allocation_id or eip,
        # if you also change the InstanceId or NetworkInterfaceId,
         # should go to Replacement flow
        if self.ALLOCATION_ID in prop_diff or self.EIP in prop_diff:
            instance_id = prop_diff.get(self.INSTANCE_ID)
            ni_id = prop_diff.get(self.NETWORK_INTERFACE_ID)

            if instance_id or ni_id:
                raise resource.UpdateReplace(self.name)

        # according to aws doc, when update the instance_id or
        # network_interface_id, if you also change the EIP or
        # ALLOCATION_ID, should go to Replacement flow
        if (self.INSTANCE_ID in prop_diff or
                self.NETWORK_INTERFACE_ID in prop_diff):
            eip = prop_diff.get(self.EIP)
            allocation_id = prop_diff.get(self.ALLOCATION_ID)
            if eip or allocation_id:
                raise resource.UpdateReplace(self.name)

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
            ni_id = self.properties[self.NETWORK_INTERFACE_ID]
            instance_id = self.properties[self.INSTANCE_ID]
            port_id, port_rsrc = self._get_port_info(ni_id, instance_id)
            if not port_id or not port_rsrc:
                LOG.warn(_('Skipping association, resource not specified'))
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
            instance_id = self.properties[self.INSTANCE_ID]
            eip = self.properties[self.EIP]
            self._nova_remove_floating_ip(instance_id,
                                          eip,
                                          ignore_not_found=True)
        elif self.properties[self.ALLOCATION_ID]:
            float_id = self.properties[self.ALLOCATION_ID]
            self._neutron_update_floating_ip(float_id,
                                             port_id=None,
                                             ignore_not_found=True)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self._validate_update_properties(prop_diff)
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
