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
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation


class VPNService(neutron.NeutronResource):
    """A resource for VPN service in Neutron.

    VPN service is a high level object that associates VPN with a specific
    subnet and router.
    """

    required_service_extension = 'vpnaas'

    entity = 'vpnservice'

    PROPERTIES = (
        NAME, DESCRIPTION, ADMIN_STATE_UP,
        SUBNET_ID, SUBNET, ROUTER_ID, ROUTER
    ) = (
        'name', 'description', 'admin_state_up',
        'subnet_id', 'subnet', 'router_id', 'router'
    )

    ATTRIBUTES = (
        ADMIN_STATE_UP_ATTR, DESCRIPTION_ATTR, NAME_ATTR, ROUTER_ID_ATTR,
        STATUS, SUBNET_ID_ATTR, TENANT_ID,
    ) = (
        'admin_state_up', 'description', 'name', 'router_id',
        'status', 'subnet_id', 'tenant_id',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the vpn service.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the vpn service.'),
            update_allowed=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Administrative state for the vpn service.'),
            default=True,
            update_allowed=True
        ),
        SUBNET_ID: properties.Schema(
            properties.Schema.STRING,
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                message=_('Use property %s.') % SUBNET,
                version='5.0.0',
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    version='2014.2'
                )
            ),
            constraints=[
                constraints.CustomConstraint('neutron.subnet')
            ]
        ),
        SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('Subnet in which the vpn service will be created.'),
            support_status=support.SupportStatus(version='2014.2'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.subnet')
            ]
        ),
        ROUTER_ID: properties.Schema(
            properties.Schema.STRING,
            _('Unique identifier for the router to which the vpn service '
              'will be inserted.'),
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='6.0.0',
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    message=_('Use property %s') % ROUTER,
                    version='2015.1',
                    previous_status=support.SupportStatus(version='2013.2'))
            ),
            constraints=[
                constraints.CustomConstraint('neutron.router')
            ]
        ),
        ROUTER: properties.Schema(
            properties.Schema.STRING,
            _('The router to which the vpn service will be inserted.'),
            support_status=support.SupportStatus(version='2015.1'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.router')
            ]
        )
    }

    attributes_schema = {
        ADMIN_STATE_UP_ATTR: attributes.Schema(
            _('The administrative state of the vpn service.'),
            type=attributes.Schema.STRING
        ),
        DESCRIPTION_ATTR: attributes.Schema(
            _('The description of the vpn service.'),
            type=attributes.Schema.STRING
        ),
        NAME_ATTR: attributes.Schema(
            _('The name of the vpn service.'),
            type=attributes.Schema.STRING
        ),
        ROUTER_ID_ATTR: attributes.Schema(
            _('The unique identifier of the router to which the vpn service '
              'was inserted.'),
            type=attributes.Schema.STRING
        ),
        STATUS: attributes.Schema(
            _('The status of the vpn service.'),
            type=attributes.Schema.STRING
        ),
        SUBNET_ID_ATTR: attributes.Schema(
            _('The unique identifier of the subnet in which the vpn service '
              'was created.'),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _('The unique identifier of the tenant owning the vpn service.'),
            type=attributes.Schema.STRING
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.SUBNET],
                value_path=[self.SUBNET_ID]
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.SUBNET],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_SUBNET
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.ROUTER],
                value_path=[self.ROUTER_ID]
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.ROUTER],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_ROUTER
            ),

        ]

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        props['subnet_id'] = props.pop(self.SUBNET)
        props['router_id'] = props.pop(self.ROUTER)
        vpnservice = self.client().create_vpnservice({'vpnservice': props})[
            'vpnservice']
        self.resource_id_set(vpnservice['id'])

    def check_create_complete(self, data):
        attributes = self._show_resource()
        status = attributes['status']
        if status == 'PENDING_CREATE':
            return False
        elif status == 'ACTIVE':
            return True
        elif status == 'ERROR':
            raise exception.ResourceInError(
                resource_status=status,
                status_reason=_('Error in VPNService'))
        else:
            raise exception.ResourceUnknownStatus(
                resource_status=status,
                result=_('VPNService creation failed'))

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client().update_vpnservice(self.resource_id,
                                            {'vpnservice': prop_diff})

    def handle_delete(self):
        try:
            self.client().delete_vpnservice(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True


class IPsecSiteConnection(neutron.NeutronResource):
    """A resource for IPsec site connection in Neutron.

    This resource has details for the site-to-site IPsec connection, including
    the peer CIDRs, MTU, peer address, DPD settings and status.
    """

    required_service_extension = 'vpnaas'

    entity = 'ipsec_site_connection'

    PROPERTIES = (
        NAME, DESCRIPTION, PEER_ADDRESS, PEER_ID, PEER_CIDRS, MTU,
        DPD, PSK, INITIATOR, ADMIN_STATE_UP, IKEPOLICY_ID,
        IPSECPOLICY_ID, VPNSERVICE_ID,
    ) = (
        'name', 'description', 'peer_address', 'peer_id', 'peer_cidrs', 'mtu',
        'dpd', 'psk', 'initiator', 'admin_state_up', 'ikepolicy_id',
        'ipsecpolicy_id', 'vpnservice_id',
    )

    _DPD_KEYS = (
        DPD_ACTIONS, DPD_INTERVAL, DPD_TIMEOUT,
    ) = (
        'actions', 'interval', 'timeout',
    )

    ATTRIBUTES = (
        ADMIN_STATE_UP_ATTR, AUTH_MODE, DESCRIPTION_ATTR, DPD_ATTR,
        IKEPOLICY_ID_ATTR, INITIATOR_ATTR, IPSECPOLICY_ID_ATTR, MTU_ATTR,
        NAME_ATTR, PEER_ADDRESS_ATTR, PEER_CIDRS_ATTR, PEER_ID_ATTR, PSK_ATTR,
        ROUTE_MODE, STATUS, TENANT_ID, VPNSERVICE_ID_ATTR,
    ) = (
        'admin_state_up', 'auth_mode', 'description', 'dpd',
        'ikepolicy_id', 'initiator', 'ipsecpolicy_id', 'mtu',
        'name', 'peer_address', 'peer_cidrs', 'peer_id', 'psk',
        'route_mode', 'status', 'tenant_id', 'vpnservice_id',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the ipsec site connection.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the ipsec site connection.'),
            update_allowed=True
        ),
        PEER_ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('Remote branch router public IPv4 address or IPv6 address or '
              'FQDN.'),
            required=True
        ),
        PEER_ID: properties.Schema(
            properties.Schema.STRING,
            _('Remote branch router identity.'),
            required=True
        ),
        PEER_CIDRS: properties.Schema(
            properties.Schema.LIST,
            _('Remote subnet(s) in CIDR format.'),
            required=True,
            schema=properties.Schema(
                properties.Schema.STRING,
                constraints=[
                    constraints.CustomConstraint('net_cidr')
                ]
            )
        ),
        MTU: properties.Schema(
            properties.Schema.INTEGER,
            _('Maximum transmission unit size (in bytes) for the ipsec site '
              'connection.'),
            default=1500
        ),
        DPD: properties.Schema(
            properties.Schema.MAP,
            _('Dead Peer Detection protocol configuration for the ipsec site '
              'connection.'),
            schema={
                DPD_ACTIONS: properties.Schema(
                    properties.Schema.STRING,
                    _('Controls DPD protocol mode.'),
                    default='hold',
                    constraints=[
                        constraints.AllowedValues(['clear', 'disabled',
                                                   'hold', 'restart',
                                                   'restart-by-peer']),
                    ]
                ),
                DPD_INTERVAL: properties.Schema(
                    properties.Schema.INTEGER,
                    _('Number of seconds for the DPD delay.'),
                    default=30
                ),
                DPD_TIMEOUT: properties.Schema(
                    properties.Schema.INTEGER,
                    _('Number of seconds for the DPD timeout.'),
                    default=120
                ),
            }
        ),
        PSK: properties.Schema(
            properties.Schema.STRING,
            _('Pre-shared key string for the ipsec site connection.'),
            required=True
        ),
        INITIATOR: properties.Schema(
            properties.Schema.STRING,
            _('Initiator state in lowercase for the ipsec site connection.'),
            default='bi-directional',
            constraints=[
                constraints.AllowedValues(['bi-directional', 'response-only']),
            ]
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Administrative state for the ipsec site connection.'),
            default=True,
            update_allowed=True
        ),
        IKEPOLICY_ID: properties.Schema(
            properties.Schema.STRING,
            _('Unique identifier for the ike policy associated with the '
              'ipsec site connection.'),
            required=True
        ),
        IPSECPOLICY_ID: properties.Schema(
            properties.Schema.STRING,
            _('Unique identifier for the ipsec policy associated with the '
              'ipsec site connection.'),
            required=True
        ),
        VPNSERVICE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Unique identifier for the vpn service associated with the '
              'ipsec site connection.'),
            required=True
        ),
    }

    attributes_schema = {
        ADMIN_STATE_UP_ATTR: attributes.Schema(
            _('The administrative state of the ipsec site connection.'),
            type=attributes.Schema.STRING
        ),
        AUTH_MODE: attributes.Schema(
            _('The authentication mode of the ipsec site connection.'),
            type=attributes.Schema.STRING
        ),
        DESCRIPTION_ATTR: attributes.Schema(
            _('The description of the ipsec site connection.'),
            type=attributes.Schema.STRING
        ),
        DPD_ATTR: attributes.Schema(
            _('The dead peer detection protocol configuration of the ipsec '
              'site connection.'),
            type=attributes.Schema.MAP
        ),
        IKEPOLICY_ID_ATTR: attributes.Schema(
            _('The unique identifier of ike policy associated with the ipsec '
              'site connection.'),
            type=attributes.Schema.STRING
        ),
        INITIATOR_ATTR: attributes.Schema(
            _('The initiator of the ipsec site connection.'),
            type=attributes.Schema.STRING
        ),
        IPSECPOLICY_ID_ATTR: attributes.Schema(
            _('The unique identifier of ipsec policy associated with the '
              'ipsec site connection.'),
            type=attributes.Schema.STRING
        ),
        MTU_ATTR: attributes.Schema(
            _('The maximum transmission unit size (in bytes) of the ipsec '
              'site connection.'),
            type=attributes.Schema.STRING
        ),
        NAME_ATTR: attributes.Schema(
            _('The name of the ipsec site connection.'),
            type=attributes.Schema.STRING
        ),
        PEER_ADDRESS_ATTR: attributes.Schema(
            _('The remote branch router public IPv4 address or IPv6 address '
              'or FQDN.'),
            type=attributes.Schema.STRING
        ),
        PEER_CIDRS_ATTR: attributes.Schema(
            _('The remote subnet(s) in CIDR format of the ipsec site '
              'connection.'),
            type=attributes.Schema.LIST
        ),
        PEER_ID_ATTR: attributes.Schema(
            _('The remote branch router identity of the ipsec site '
              'connection.'),
            type=attributes.Schema.STRING
        ),
        PSK_ATTR: attributes.Schema(
            _('The pre-shared key string of the ipsec site connection.'),
            type=attributes.Schema.STRING
        ),
        ROUTE_MODE: attributes.Schema(
            _('The route mode of the ipsec site connection.'),
            type=attributes.Schema.STRING
        ),
        STATUS: attributes.Schema(
            _('The status of the ipsec site connection.'),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _('The unique identifier of the tenant owning the ipsec site '
              'connection.'),
            type=attributes.Schema.STRING
        ),
        VPNSERVICE_ID_ATTR: attributes.Schema(
            _('The unique identifier of vpn service associated with the ipsec '
              'site connection.'),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        ipsec_site_connection = self.client().create_ipsec_site_connection(
            {'ipsec_site_connection': props})['ipsec_site_connection']
        self.resource_id_set(ipsec_site_connection['id'])

    def check_create_complete(self, data):
        attributes = self._show_resource()
        status = attributes['status']

        if status == 'PENDING_CREATE':
            return False
        elif status == 'ACTIVE':
            return True
        elif status == 'ERROR':
            raise exception.ResourceInError(
                resource_status=status,
                status_reason=_('Error in IPsecSiteConnection'))
        else:
            raise exception.ResourceUnknownStatus(
                resource_status=status,
                result=_('IPsecSiteConnection creation failed'))

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().update_ipsec_site_connection(
                self.resource_id, {'ipsec_site_connection': prop_diff})

    def handle_delete(self):
        try:
            self.client().delete_ipsec_site_connection(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True


class IKEPolicy(neutron.NeutronResource):
    """A resource for IKE policy in Neutron.

    The Internet Key Exchange policy identifies the authentication and
    encryption algorithm used during phase one and phase two negotiation of a
    VPN connection.
    """

    required_service_extension = 'vpnaas'

    entity = 'ikepolicy'

    PROPERTIES = (
        NAME, DESCRIPTION, AUTH_ALGORITHM, ENCRYPTION_ALGORITHM,
        PHASE1_NEGOTIATION_MODE, LIFETIME, PFS, IKE_VERSION,
    ) = (
        'name', 'description', 'auth_algorithm', 'encryption_algorithm',
        'phase1_negotiation_mode', 'lifetime', 'pfs', 'ike_version',
    )

    _LIFETIME_KEYS = (
        LIFETIME_UNITS, LIFETIME_VALUE,
    ) = (
        'units', 'value',
    )

    ATTRIBUTES = (
        AUTH_ALGORITHM_ATTR, DESCRIPTION_ATTR, ENCRYPTION_ALGORITHM_ATTR,
        IKE_VERSION_ATTR, LIFETIME_ATTR, NAME_ATTR, PFS_ATTR,
        PHASE1_NEGOTIATION_MODE_ATTR, TENANT_ID,
    ) = (
        'auth_algorithm', 'description', 'encryption_algorithm',
        'ike_version', 'lifetime', 'name', 'pfs',
        'phase1_negotiation_mode', 'tenant_id',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the ike policy.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the ike policy.'),
            update_allowed=True
        ),
        AUTH_ALGORITHM: properties.Schema(
            properties.Schema.STRING,
            _('Authentication hash algorithm for the ike policy.'),
            default='sha1',
            constraints=[
                constraints.AllowedValues(['sha1', 'sha256',
                                           'sha384', 'sha512']),
            ],
            update_allowed=True
        ),
        ENCRYPTION_ALGORITHM: properties.Schema(
            properties.Schema.STRING,
            _('Encryption algorithm for the ike policy.'),
            default='aes-128',
            constraints=[
                constraints.AllowedValues(['3des', 'aes-128', 'aes-192',
                                           'aes-256']),
            ]
        ),
        PHASE1_NEGOTIATION_MODE: properties.Schema(
            properties.Schema.STRING,
            _('Negotiation mode for the ike policy.'),
            default='main',
            constraints=[
                constraints.AllowedValues(['main']),
            ]
        ),
        LIFETIME: properties.Schema(
            properties.Schema.MAP,
            _('Safety assessment lifetime configuration for the ike policy.'),
            schema={
                LIFETIME_UNITS: properties.Schema(
                    properties.Schema.STRING,
                    _('Safety assessment lifetime units.'),
                    default='seconds',
                    constraints=[
                        constraints.AllowedValues(['seconds', 'kilobytes']),
                    ]
                ),
                LIFETIME_VALUE: properties.Schema(
                    properties.Schema.INTEGER,
                    _('Safety assessment lifetime value in specified '
                      'units.'),
                    default=3600
                ),
            }
        ),
        PFS: properties.Schema(
            properties.Schema.STRING,
            _('Perfect forward secrecy in lowercase for the ike policy.'),
            default='group5',
            constraints=[
                constraints.AllowedValues(['group2', 'group5', 'group14']),
            ]
        ),
        IKE_VERSION: properties.Schema(
            properties.Schema.STRING,
            _('Version for the ike policy.'),
            default='v1',
            constraints=[
                constraints.AllowedValues(['v1', 'v2']),
            ]
        ),
    }

    attributes_schema = {
        AUTH_ALGORITHM_ATTR: attributes.Schema(
            _('The authentication hash algorithm used by the ike policy.'),
            type=attributes.Schema.STRING
        ),
        DESCRIPTION_ATTR: attributes.Schema(
            _('The description of the ike policy.'),
            type=attributes.Schema.STRING
        ),
        ENCRYPTION_ALGORITHM_ATTR: attributes.Schema(
            _('The encryption algorithm used by the ike policy.'),
            type=attributes.Schema.STRING
        ),
        IKE_VERSION_ATTR: attributes.Schema(
            _('The version of the ike policy.'),
            type=attributes.Schema.STRING
        ),
        LIFETIME_ATTR: attributes.Schema(
            _('The safety assessment lifetime configuration for the ike '
              'policy.'),
            type=attributes.Schema.MAP
        ),
        NAME_ATTR: attributes.Schema(
            _('The name of the ike policy.'),
            type=attributes.Schema.STRING
        ),
        PFS_ATTR: attributes.Schema(
            _('The perfect forward secrecy of the ike policy.'),
            type=attributes.Schema.STRING
        ),
        PHASE1_NEGOTIATION_MODE_ATTR: attributes.Schema(
            _('The negotiation mode of the ike policy.'),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _('The unique identifier of the tenant owning the ike policy.'),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        ikepolicy = self.client().create_ikepolicy({'ikepolicy': props})[
            'ikepolicy']
        self.resource_id_set(ikepolicy['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().update_ikepolicy(self.resource_id,
                                           {'ikepolicy': prop_diff})

    def handle_delete(self):
        try:
            self.client().delete_ikepolicy(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True


class IPsecPolicy(neutron.NeutronResource):
    """A resource for IPsec policy in Neutron.

    The IP security policy specifying the authentication and encryption
    algorithm, and encapsulation mode used for the established VPN connection.
    """

    required_service_extension = 'vpnaas'

    entity = 'ipsecpolicy'

    PROPERTIES = (
        NAME, DESCRIPTION, TRANSFORM_PROTOCOL, ENCAPSULATION_MODE,
        AUTH_ALGORITHM, ENCRYPTION_ALGORITHM, LIFETIME, PFS,
    ) = (
        'name', 'description', 'transform_protocol', 'encapsulation_mode',
        'auth_algorithm', 'encryption_algorithm', 'lifetime', 'pfs',
    )

    _LIFETIME_KEYS = (
        LIFETIME_UNITS, LIFETIME_VALUE,
    ) = (
        'units', 'value',
    )

    ATTRIBUTES = (
        AUTH_ALGORITHM_ATTR, DESCRIPTION_ATTR, ENCAPSULATION_MODE_ATTR,
        ENCRYPTION_ALGORITHM_ATTR, LIFETIME_ATTR, NAME_ATTR, PFS_ATTR,
        TENANT_ID, TRANSFORM_PROTOCOL_ATTR,
    ) = (
        'auth_algorithm', 'description', 'encapsulation_mode',
        'encryption_algorithm', 'lifetime', 'name', 'pfs',
        'tenant_id', 'transform_protocol',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the ipsec policy.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the ipsec policy.'),
            update_allowed=True
        ),
        TRANSFORM_PROTOCOL: properties.Schema(
            properties.Schema.STRING,
            _('Transform protocol for the ipsec policy.'),
            default='esp',
            constraints=[
                constraints.AllowedValues(['esp', 'ah', 'ah-esp']),
            ]
        ),
        ENCAPSULATION_MODE: properties.Schema(
            properties.Schema.STRING,
            _('Encapsulation mode for the ipsec policy.'),
            default='tunnel',
            constraints=[
                constraints.AllowedValues(['tunnel', 'transport']),
            ]
        ),
        AUTH_ALGORITHM: properties.Schema(
            properties.Schema.STRING,
            _('Authentication hash algorithm for the ipsec policy.'),
            default='sha1',
            constraints=[
                constraints.AllowedValues(['sha1']),
            ]
        ),
        ENCRYPTION_ALGORITHM: properties.Schema(
            properties.Schema.STRING,
            _('Encryption algorithm for the ipsec policy.'),
            default='aes-128',
            constraints=[
                constraints.AllowedValues(['3des', 'aes-128', 'aes-192',
                                           'aes-256']),
            ]
        ),
        LIFETIME: properties.Schema(
            properties.Schema.MAP,
            _('Safety assessment lifetime configuration for the ipsec '
              'policy.'),
            schema={
                LIFETIME_UNITS: properties.Schema(
                    properties.Schema.STRING,
                    _('Safety assessment lifetime units.'),
                    default='seconds',
                    constraints=[
                        constraints.AllowedValues(['seconds',
                                                   'kilobytes']),
                    ]
                ),
                LIFETIME_VALUE: properties.Schema(
                    properties.Schema.INTEGER,
                    _('Safety assessment lifetime value in specified '
                      'units.'),
                    default=3600
                ),
            }
        ),
        PFS: properties.Schema(
            properties.Schema.STRING,
            _('Perfect forward secrecy for the ipsec policy.'),
            default='group5',
            constraints=[
                constraints.AllowedValues(['group2', 'group5', 'group14']),
            ]
        ),
    }

    attributes_schema = {
        AUTH_ALGORITHM_ATTR: attributes.Schema(
            _('The authentication hash algorithm of the ipsec policy.'),
            type=attributes.Schema.STRING
        ),
        DESCRIPTION_ATTR: attributes.Schema(
            _('The description of the ipsec policy.'),
            type=attributes.Schema.STRING
        ),
        ENCAPSULATION_MODE_ATTR: attributes.Schema(
            _('The encapsulation mode of the ipsec policy.'),
            type=attributes.Schema.STRING
        ),
        ENCRYPTION_ALGORITHM_ATTR: attributes.Schema(
            _('The encryption algorithm of the ipsec policy.'),
            type=attributes.Schema.STRING
        ),
        LIFETIME_ATTR: attributes.Schema(
            _('The safety assessment lifetime configuration of the ipsec '
              'policy.'),
            type=attributes.Schema.MAP
        ),
        NAME_ATTR: attributes.Schema(
            _('The name of the ipsec policy.'),
            type=attributes.Schema.STRING
        ),
        PFS_ATTR: attributes.Schema(
            _('The perfect forward secrecy of the ipsec policy.'),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _('The unique identifier of the tenant owning the ipsec policy.'),
            type=attributes.Schema.STRING
        ),
        TRANSFORM_PROTOCOL_ATTR: attributes.Schema(
            _('The transform protocol of the ipsec policy.'),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        ipsecpolicy = self.client().create_ipsecpolicy(
            {'ipsecpolicy': props})['ipsecpolicy']
        self.resource_id_set(ipsecpolicy['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().update_ipsecpolicy(self.resource_id,
                                             {'ipsecpolicy': prop_diff})

    def handle_delete(self):
        try:
            self.client().delete_ipsecpolicy(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True


def resource_mapping():
    return {
        'OS::Neutron::VPNService': VPNService,
        'OS::Neutron::IPsecSiteConnection': IPsecSiteConnection,
        'OS::Neutron::IKEPolicy': IKEPolicy,
        'OS::Neutron::IPsecPolicy': IPsecPolicy,
    }
