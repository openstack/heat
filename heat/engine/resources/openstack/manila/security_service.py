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

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class SecurityService(resource.Resource):
    """A resource that implements security service of Manila.

    A security_service is a set of options that defines a security domain
    for a particular shared filesystem protocol, such as an
    Active Directory domain or a Kerberos domain.
    """

    support_status = support.SupportStatus(version='5.0.0')

    PROPERTIES = (
        NAME, TYPE, DNS_IP, SERVER, DOMAIN, USER,
        PASSWORD, DESCRIPTION
    ) = (
        'name', 'type', 'dns_ip', 'server', 'domain', 'user',
        'password', 'description'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Security service name.'),
            update_allowed=True
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Security service type.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['ldap', 'kerberos',
                                           'active_directory'])
            ]
        ),
        DNS_IP: properties.Schema(
            properties.Schema.STRING,
            _('DNS IP address used inside tenant\'s network.'),
            update_allowed=True
        ),
        SERVER: properties.Schema(
            properties.Schema.STRING,
            _('Security service IP address or hostname.'),
            update_allowed=True
        ),
        DOMAIN: properties.Schema(
            properties.Schema.STRING,
            _('Security service domain.'),
            update_allowed=True
        ),
        USER: properties.Schema(
            properties.Schema.STRING,
            _('Security service user or group used by tenant.'),
            update_allowed=True
        ),
        PASSWORD: properties.Schema(
            properties.Schema.STRING,
            _('Password used by user.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Security service description.'),
            update_allowed=True
        )
    }

    default_client_name = 'manila'

    entity = 'security_services'

    def handle_create(self):
        args = dict((k, v) for k, v in self.properties.items()
                    if v is not None)
        security_service = self.client().security_services.create(**args)
        self.resource_id_set(security_service.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().security_services.update(self.resource_id,
                                                   **prop_diff)


def resource_mapping():
    return {
        'OS::Manila::SecurityService': SecurityService
    }
