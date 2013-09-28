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
from heat.engine.resources.neutron import neutron
from heat.engine import scheduler

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class VPNService(neutron.NeutronResource):
    """
    A resource for VPN service in Neutron.
    """

    properties_schema = {
        'name': {
            'Type': 'String',
            'Description': _('Name for the vpn service.')
        },
        'description': {
            'Type': 'String',
            'Description': _('Description for the vpn service.')
        },
        'admin_state_up': {
            'Type': 'Boolean',
            'Default': True,
            'Description': _('Administrative state for the vpn service.')
        },
        'subnet_id': {
            'Type': 'String',
            'Required': True,
            'Description': _('Unique identifier for the subnet in which the '
                             'vpn service will be created.')
        },
        'router_id': {
            'Type': 'String',
            'Required': True,
            'Description': _('Unique identifier for the router to which the '
                             'vpn service will be inserted.')
        }
    }

    attributes_schema = {
        'admin_state_up': _('The administrative state of the vpn service.'),
        'description': _('The description of the vpn service.'),
        'name': _('The name of the vpn service.'),
        'router_id': _('The unique identifier of the router to which the vpn '
                       'service was inserted.'),
        'status': _('The status of the vpn service.'),
        'subnet_id': _('The unique identifier of the subnet in which the vpn '
                       'service was created.'),
        'tenant_id': _('The unique identifier of the tenant owning the vpn '
                       'service.')
    }

    update_allowed_keys = ('Properties',)

    update_allowed_properties = ('name', 'description', 'admin_state_up',)

    def _show_resource(self):
        return self.neutron().show_vpnservice(self.resource_id)['vpnservice']

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        vpnservice = self.neutron().create_vpnservice({'vpnservice': props})[
            'vpnservice']
        self.resource_id_set(vpnservice['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.neutron().update_vpnservice(self.resource_id,
                                             {'vpnservice': prop_diff})

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_vpnservice(self.resource_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex
        else:
            return scheduler.TaskRunner(self._confirm_delete)()


class IPsecSiteConnection(neutron.NeutronResource):
    """
    A resource for IPsec site connection in Neutron.
    """

    dpd_schema = {
        'actions': {
            'Type': 'String',
            'AllowedValues': ['clear', 'disabled', 'hold', 'restart',
                              'restart-by-peer'],
            'Default': 'hold',
            'Description': _('Controls DPD protocol mode.')
        },
        'interval': {
            'Type': 'Integer',
            'Default': 30,
            'Description': _('Number of seconds for the DPD delay.')
        },
        'timeout': {
            'Type': 'Integer',
            'Default': 120,
            'Description': _('Number of seconds for the DPD timeout.')
        },
    }

    properties_schema = {
        'name': {
            'Type': 'String',
            'Description': _('Name for the ipsec site connection.')
        },
        'description': {
            'Type': 'String',
            'Description': _('Description for the ipsec site connection.')
        },
        'peer_address': {
            'Type': 'String',
            'Required': True,
            'Description': _('Remote branch router public IPv4 address or '
                             'IPv6 address or FQDN.')
        },
        'peer_id': {
            'Type': 'String',
            'Required': True,
            'Description': _('Remote branch router identity.')
        },
        'peer_cidrs': {
            'Type': 'List',
            'Required': True,
            'Description': _('Remote subnet(s) in CIDR format.')
        },
        'mtu': {
            'Type': 'Integer',
            'Default': 1500,
            'Description': _('Maximum transmission unit size (in bytes) for '
                             'the ipsec site connection.')
        },
        'dpd': {
            'Type': 'Map',
            'Schema': dpd_schema,
            'Description': _('Dead Peer Detection protocol configuration for '
                             'the ipsec site connection.')
        },
        'psk': {
            'Type': 'String',
            'Required': True,
            'Description': _('Pre-shared key string for the ipsec site '
                             'connection.')
        },
        'initiator': {
            'Type': 'String',
            'AllowedValues': ['bi-directional', 'response-only'],
            'Default': 'bi-directional',
            'Description': _('Initiator state in lowercase for the ipsec site '
                             'connection.')
        },
        'admin_state_up': {
            'Type': 'Boolean',
            'Default': True,
            'Description': _('Administrative state for the ipsec site '
                             'connection.')
        },
        'ikepolicy_id': {
            'Type': 'String',
            'Required': True,
            'Description': _('Unique identifier for the ike policy associated '
                             'with the ipsec site connection.')
        },
        'ipsecpolicy_id': {
            'Type': 'String',
            'Required': True,
            'Description': _('Unique identifier for the ipsec policy '
                             'associated with the ipsec site connection.')
        },
        'vpnservice_id': {
            'Type': 'String',
            'Required': True,
            'Description': _('Unique identifier for the vpn service '
                             'associated with the ipsec site connection.')
        }
    }

    attributes_schema = {
        'admin_state_up': _('The administrative state of the ipsec site '
                            'connection.'),
        'auth_mode': _('The authentication mode of the ipsec site '
                       'connection.'),
        'description': _('The description of the ipsec site connection.'),
        'dpd': _('The dead peer detection protocol configuration of the ipsec '
                 'site connection.'),
        'ikepolicy_id': _('The unique identifier of ike policy associated '
                          'with the ipsec site connection.'),
        'initiator': _('The initiator of the ipsec site connection.'),
        'ipsecpolicy_id': _('The unique identifier of ipsec policy '
                            'associated with the ipsec site connection.'),
        'mtu': _('The maximum transmission unit size (in bytes) of the ipsec '
                 'site connection.'),
        'name': _('The name of the ipsec site connection.'),
        'peer_address': _('The remote branch router public IPv4 address or '
                          'IPv6 address or FQDN.'),
        'peer_cidrs': _('The remote subnet(s) in CIDR format of the ipsec '
                        'site connection.'),
        'peer_id': _('The remote branch router identity of the ipsec site '
                     'connection.'),
        'psk': _('The pre-shared key string of the ipsec site connection.'),
        'route_mode': _('The route mode of the ipsec site connection.'),
        'status': _('The status of the ipsec site connection.'),
        'tenant_id': _('The unique identifier of the tenant owning the ipsec '
                       'site connection.'),
        'vpnservice_id': _('The unique identifier of vpn service associated '
                           'with the ipsec site connection.')
    }

    update_allowed_keys = ('Properties',)

    update_allowed_properties = ('name', 'description', 'admin_state_up',)

    def _show_resource(self):
        return self.neutron().show_ipsec_site_connection(self.resource_id)[
            'ipsec_site_connection']

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        ipsec_site_connection = self.neutron().create_ipsec_site_connection(
            {'ipsec_site_connection': props})['ipsec_site_connection']
        self.resource_id_set(ipsec_site_connection['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.neutron().update_ipsec_site_connection(
                self.resource_id, {'ipsec_site_connection': prop_diff})

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_ipsec_site_connection(self.resource_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex
        else:
            return scheduler.TaskRunner(self._confirm_delete)()


class IKEPolicy(neutron.NeutronResource):
    """
    A resource for IKE policy in Neutron.
    """

    lifetime_schema = {
        'units': {
            'Type': 'String',
            'AllowedValues': ['seconds', 'kilobytes'],
            'Default': 'seconds',
            'Description': _('Safety assessment lifetime units.')
        },
        'value': {
            'Type': 'Integer',
            'Default': 3600,
            'Description': _('Safety assessment lifetime value in specified '
                             'units.')
        },
    }

    properties_schema = {
        'name': {
            'Type': 'String',
            'Description': _('Name for the ike policy.')
        },
        'description': {
            'Type': 'String',
            'Description': _('Description for the ike policy.')
        },
        'auth_algorithm': {
            'Type': 'String',
            'AllowedValues': ['sha1'],
            'Default': 'sha1',
            'Description': _('Authentication hash algorithm for the ike '
                             'policy.')
        },
        'encryption_algorithm': {
            'Type': 'String',
            'AllowedValues': ['3des', 'aes-128', 'aes-192', 'aes-256'],
            'Default': 'aes-128',
            'Description': _('Encryption algorithm for the ike policy.')
        },
        'phase1_negotiation_mode': {
            'Type': 'String',
            'AllowedValues': ['main'],
            'Default': 'main',
            'Description': _('Negotiation mode for the ike policy.')
        },
        'lifetime': {
            'Type': 'Map',
            'Schema': lifetime_schema,
            'Description': _('Safety assessment lifetime configuration for '
                             'the ike policy.')
        },
        'pfs': {
            'Type': 'String',
            'AllowedValues': ['group2', 'group5', 'group14'],
            'Default': 'group5',
            'Description': _('Perfect forward secrecy in lowercase for the '
                             'ike policy.')
        },
        'ike_version': {
            'Type': 'String',
            'AllowedValues': ['v1', 'v2'],
            'Default': 'v1',
            'Description': _('Version for the ike policy.')
        }
    }

    attributes_schema = {
        'auth_algorithm': _('The authentication hash algorithm used by the ike'
                            ' policy.'),
        'description': _('The description of the ike policy.'),
        'encryption_algorithm': _('The encryption algorithm used by the ike '
                                  'policy.'),
        'ike_version': _('The version of the ike policy.'),
        'lifetime': _('The safety assessment lifetime configuration for the '
                      'ike policy.'),
        'name': _('The name of the ike policy.'),
        'pfs': _('The perfect forward secrecy of the ike policy.'),
        'phase1_negotiation_mode': _('The negotiation mode of the ike '
                                     'policy.'),
        'tenant_id': _('The unique identifier of the tenant owning the ike '
                       'policy.'),
    }

    update_allowed_keys = ('Properties',)

    update_allowed_properties = ('name', 'description',)

    def _show_resource(self):
        return self.neutron().show_ikepolicy(self.resource_id)['ikepolicy']

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        ikepolicy = self.neutron().create_ikepolicy({'ikepolicy': props})[
            'ikepolicy']
        self.resource_id_set(ikepolicy['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.neutron().update_ikepolicy(self.resource_id,
                                            {'ikepolicy': prop_diff})

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_ikepolicy(self.resource_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex
        else:
            return scheduler.TaskRunner(self._confirm_delete)()


class IPsecPolicy(neutron.NeutronResource):
    """
    A resource for IPsec policy in Neutron.
    """

    lifetime_schema = {
        'units': {
            'Type': 'String',
            'AllowedValues': ['seconds', 'kilobytes'],
            'Default': 'seconds',
            'Description': _('Safety assessment lifetime units.')
        },
        'value': {
            'Type': 'Integer',
            'Default': 3600,
            'Description': _('Safety assessment lifetime value in specified '
                             'units.')
        },
    }

    properties_schema = {
        'name': {
            'Type': 'String',
            'Description': _('Name for the ipsec policy.')
        },
        'description': {
            'Type': 'String',
            'Description': _('Description for the ipsec policy.')
        },
        'transform_protocol': {
            'Type': 'String',
            'AllowedValues': ['esp', 'ah', 'ah-esp'],
            'Default': 'esp',
            'Description': _('Transform protocol for the ipsec policy.')
        },
        'encapsulation_mode': {
            'Type': 'String',
            'AllowedValues': ['tunnel', 'transport'],
            'Default': 'tunnel',
            'Description': _('Encapsulation mode for the ipsec policy.')
        },
        'auth_algorithm': {
            'Type': 'String',
            'AllowedValues': ['sha1'],
            'Default': 'sha1',
            'Description': _('Authentication hash algorithm for the ipsec '
                             'policy.')
        },
        'encryption_algorithm': {
            'Type': 'String',
            'AllowedValues': ['3des', 'aes-128', 'aes-192', 'aes-256'],
            'Default': 'aes-128',
            'Description': _('Encryption algorithm for the ipsec policy.')
        },
        'lifetime': {
            'Type': 'Map',
            'Schema': lifetime_schema,
            'Description': _('Safety assessment lifetime configuration for '
                             'the ipsec policy.')
        },
        'pfs': {
            'Type': 'String',
            'AllowedValues': ['group2', 'group5', 'group14'],
            'Default': 'group5',
            'Description': _('Perfect forward secrecy for the ipsec policy.')
        }
    }

    attributes_schema = {
        'auth_algorithm': _('The authentication hash algorithm of the ipsec '
                            'policy.'),
        'description': _('The description of the ipsec policy.'),
        'encapsulation_mode': _('The encapsulation mode of the ipsec policy.'),
        'encryption_algorithm': _('The encryption algorithm of the ipsec '
                                  'policy.'),
        'lifetime': _('The safety assessment lifetime configuration of the '
                      'ipsec policy.'),
        'name': _('The name of the ipsec policy.'),
        'pfs': _('The perfect forward secrecy of the ipsec policy.'),
        'tenant_id': _('The unique identifier of the tenant owning the '
                       'ipsec policy.'),
        'transform_protocol': _('The transform protocol of the ipsec policy.')
    }

    update_allowed_keys = ('Properties',)

    update_allowed_properties = ('name', 'description',)

    def _show_resource(self):
        return self.neutron().show_ipsecpolicy(self.resource_id)['ipsecpolicy']

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        ipsecpolicy = self.neutron().create_ipsecpolicy(
            {'ipsecpolicy': props})['ipsecpolicy']
        self.resource_id_set(ipsecpolicy['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.neutron().update_ipsecpolicy(self.resource_id,
                                              {'ipsecpolicy': prop_diff})

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_ipsecpolicy(self.resource_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex
        else:
            return scheduler.TaskRunner(self._confirm_delete)()


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::VPNService': VPNService,
        'OS::Neutron::IPsecSiteConnection': IPsecSiteConnection,
        'OS::Neutron::IKEPolicy': IKEPolicy,
        'OS::Neutron::IPsecPolicy': IPsecPolicy,
    }
