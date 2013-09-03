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

    properties_schema = {'name': {'Type': 'String'},
                         'description': {'Type': 'String'},
                         'admin_state_up': {'Type': 'Boolean',
                                            'Default': True},
                         'subnet_id': {'Type': 'String',
                                       'Required': True},
                         'router_id': {'Type': 'String',
                                       'Required': True}}

    attributes_schema = {
        'admin_state_up': 'the administrative state of the vpn service',
        'description': 'description of the vpn service',
        'id': 'unique identifier for the vpn service',
        'name': 'name for the vpn service',
        'router_id': 'unique identifier for router used to create the vpn'
                     ' service',
        'status': 'the status of the vpn service',
        'subnet_id': 'unique identifier for subnet used to create the vpn'
                     ' service',
        'tenant_id': 'tenant owning the vpn service'
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
        'actions': {'Type': 'String',
                    'AllowedValues': ['clear',
                                      'disabled',
                                      'hold',
                                      'restart',
                                      'restart-by-peer'],
                    'Default': 'hold'},
        'interval': {'Type': 'Integer',
                     'Default': 30},
        'timeout': {'Type': 'Integer',
                    'Default': 120},
    }

    properties_schema = {'name': {'Type': 'String'},
                         'description': {'Type': 'String'},
                         'peer_address': {'Type': 'String',
                                          'Required': True},
                         'peer_id': {'Type': 'String',
                                     'Required': True},
                         'peer_cidrs': {'Type': 'List',
                                        'Required': True},
                         'mtu': {'Type': 'Integer',
                                 'Default': 1500},
                         'dpd': {'Type': 'Map', 'Schema': dpd_schema},
                         'psk': {'Type': 'String',
                                 'Required': True},
                         'initiator': {'Type': 'String',
                                       'AllowedValues': ['bi-directional',
                                                         'response-only'],
                                       'Default': 'bi-directional'},
                         'admin_state_up': {'Type': 'Boolean',
                                            'Default': True},
                         'ikepolicy_id': {'Type': 'String',
                                          'Required': True},
                         'ipsecpolicy_id': {'Type': 'String',
                                            'Required': True},
                         'vpnservice_id': {'Type': 'String',
                                           'Required': True}}

    attributes_schema = {
        'admin_state_up': 'the administrative state of the ipsec site'
                          ' connection',
        'auth_mode': 'authentication mode used by the ipsec site connection',
        'description': 'description of the ipsec site connection',
        'dpd': 'configuration of dead peer detection protocol',
        'id': 'unique identifier for the ipsec site connection',
        'ikepolicy_id': 'unique identifier for ike policy used to create the'
                        ' ipsec site connection',
        'initiator': 'initiator of the ipsec site connection',
        'ipsecpolicy_id': 'unique identifier for ipsec policy used to create'
                          ' the ipsec site connection',
        'mtu': 'maximum transmission unit to address fragmentation',
        'name': 'name for the ipsec site connection',
        'peer_address': 'peer vpn gateway public address or FQDN',
        'peer_cidrs': 'peer private cidrs',
        'peer_id': 'peer identifier (name, string or FQDN)',
        'psk': 'pre-shared-key used to create the ipsec site connection',
        'route_mode': 'route mode used to create the ipsec site connection',
        'status': 'the status of the ipsec site connection',
        'tenant_id': 'tenant owning the ipsec site connection',
        'vpnservice_id': 'unique identifier for vpn service used to create the'
                         ' ipsec site connection'
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
        'units': {'Type': 'String', 'AllowedValues': ['seconds', 'kilobytes'],
                  'Default': 'seconds'},
        'value': {'Type': 'Integer', 'Default': 3600},
    }

    properties_schema = {'name': {'Type': 'String'},
                         'description': {'Type': 'String'},
                         'auth_algorithm': {'Type': 'String',
                                            'AllowedValues': ['sha1'],
                                            'Default': 'sha1'},
                         'encryption_algorithm': {'Type': 'String',
                                                  'AllowedValues': ['3des',
                                                                    'aes-128',
                                                                    'aes-192',
                                                                    'aes-256'],
                                                  'Default': 'aes-128'},
                         'phase1_negotiation_mode': {'Type': 'String',
                                                     'AllowedValues': ['main'],
                                                     'Default': 'main'},
                         'lifetime': {'Type': 'Map',
                                      'Schema': lifetime_schema},
                         'pfs': {'Type': 'String',
                                 'AllowedValues': ['group2', 'group5',
                                                   'group14'],
                                 'Default': 'group5'},
                         'ike_version': {'Type': 'String',
                                         'AllowedValues': ['v1', 'v2'],
                                         'Default': 'v1'}}

    attributes_schema = {
        'auth_algorithm': 'authentication hash algorithm used by the ike'
                          ' policy',
        'description': 'description of the ike policy',
        'encryption_algorithm': 'encryption algorithm used by the ike policy',
        'id': 'unique identifier for the ike policy',
        'ike_version': 'version of the ike policy',
        'lifetime': 'configuration of safety assessment lifetime for the ike'
                    ' policy',
        'name': 'name for the ike policy',
        'pfs': 'perfect forward secrecy for the ike policy',
        'phase1_negotiation_mode': 'negotiation mode for the ike policy',
        'tenant_id': 'tenant owning the ike policy',
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
        'units': {'Type': 'String', 'AllowedValues': ['seconds', 'kilobytes'],
                  'Default': 'seconds'},
        'value': {'Type': 'Integer', 'Default': 3600},
    }

    properties_schema = {'name': {'Type': 'String'},
                         'description': {'Type': 'String'},
                         'transform_protocol': {'Type': 'String',
                                                'AllowedValues': ['esp', 'ah',
                                                                  'ah-esp'],
                                                'Default': 'esp'},
                         'encapsulation_mode': {'Type': 'String',
                                                'AllowedValues': ['tunnel',
                                                                  'transport'],
                                                'Default': 'tunnel'},
                         'auth_algorithm': {'Type': 'String',
                                            'AllowedValues': ['sha1'],
                                            'Default': 'sha1'},
                         'encryption_algorithm': {'Type': 'String',
                                                  'AllowedValues': ['3des',
                                                                    'aes-128',
                                                                    'aes-192',
                                                                    'aes-256'],
                                                  'Default': 'aes-128'},
                         'lifetime': {'Type': 'Map',
                                      'Schema': lifetime_schema},
                         'pfs': {'Type': 'String',
                                 'AllowedValues': ['group2', 'group5',
                                                   'group14'],
                                 'Default': 'group5'}}

    attributes_schema = {
        'auth_algorithm': 'authentication hash algorithm used by the ipsec'
                          ' policy',
        'description': 'description of the ipsec policy',
        'encapsulation_mode': 'encapsulation mode for the ipsec policy',
        'encryption_algorithm': 'encryption algorithm for the ipsec policy',
        'id': 'unique identifier for this ipsec policy',
        'lifetime': 'configuration of safety assessment lifetime for the ipsec'
                    ' policy',
        'name': 'name for the ipsec policy',
        'pfs': 'perfect forward secrecy for the ipsec policy',
        'tenant_id': 'tenant owning the ipsec policy',
        'transform_protocol': 'transform protocol for the ipsec policy'
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
