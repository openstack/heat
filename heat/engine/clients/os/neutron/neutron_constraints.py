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
#
#    Copyright 2015 IBM Corp.

from neutronclient.common import exceptions as qe

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints

CLIENT_NAME = 'neutron'


class NeutronConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (qe.NeutronClientException,
                           exception.EntityNotFound)
    resource_name = None
    extension = None

    def validate_with_client(self, client, value):
        neutron_plugin = client.client_plugin(CLIENT_NAME)
        if (self.extension and
                not neutron_plugin.has_extension(self.extension)):
            raise exception.EntityNotFound(entity='neutron extension',
                                           name=self.extension)
        neutron_plugin.find_resourceid_by_name_or_id(
            self.resource_name, value)


class NeutronExtConstraint(NeutronConstraint):

    def validate_with_client(self, client, value):
        neutron_plugin = client.client_plugin(CLIENT_NAME)
        if (self.extension and
                not neutron_plugin.has_extension(self.extension)):
            raise exception.EntityNotFound(entity='neutron extension',
                                           name=self.extension)
        neutron_plugin.resolve_ext_resource(self.resource_name, value)


class NetworkConstraint(NeutronConstraint):
    resource_name = 'network'


class PortConstraint(NeutronConstraint):
    resource_name = 'port'


class RouterConstraint(NeutronConstraint):
    resource_name = 'router'


class SubnetConstraint(NeutronConstraint):
    resource_name = 'subnet'


class SubnetPoolConstraint(NeutronConstraint):
    resource_name = 'subnetpool'


class SecurityGroupConstraint(NeutronConstraint):
    resource_name = 'security_group'


class AddressScopeConstraint(NeutronConstraint):
    resource_name = 'address_scope'
    extension = 'address-scope'


class QoSPolicyConstraint(NeutronConstraint):
    resource_name = 'policy'
    extension = 'qos'


class PortPairConstraint(NeutronExtConstraint):
    resource_name = 'port_pair'
    extension = 'sfc'


class PortPairGroupConstraint(NeutronExtConstraint):
    resource_name = 'port_pair_group'
    extension = 'sfc'


class FlowClassifierConstraint(NeutronExtConstraint):
    resource_name = 'flow_classifier'
    extension = 'sfc'


class ProviderConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.StackValidationFailed,)
    service_type = None

    def validate_with_client(self, client, value):
        params = {}
        neutron_client = client.client(CLIENT_NAME)
        if self.service_type:
            params['service_type'] = self.service_type
        providers = neutron_client.list_service_providers(
            retrieve_all=True,
            **params
        )['service_providers']
        names = [provider['name'] for provider in providers]
        if value not in names:
            not_found_message = (
                _("Unable to find neutron provider '%(provider)s', "
                  "available providers are %(providers)s.") %
                {'provider': value, 'providers': names}
            )
            raise exception.StackValidationFailed(message=not_found_message)


class LBaasV1ProviderConstraint(ProviderConstraint):
    service_type = 'LOADBALANCER'
