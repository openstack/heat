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
from heat.engine import constraints


class NetworkConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (qe.NeutronClientException,
                           exception.EntityNotFound,
                           exception.PhysicalResourceNameAmbiguity)

    def validate_with_client(self, client, value):
        try:
            client.client('neutron')
        except Exception:
            # is not using neutron
            client.client_plugin('nova').get_nova_network_id(value)
        else:
            neutron_plugin = client.client_plugin('neutron')
            neutron_plugin.find_resourceid_by_name_or_id(
                'network', value, cmd_resource=None)


class NeutronConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (qe.NeutronClientException,
                           exception.EntityNotFound)
    resource_name = None
    cmd_resource = None
    extension = None

    def validate_with_client(self, client, value):
        neutron_plugin = client.client_plugin('neutron')
        if (self.extension and
                not neutron_plugin.has_extension(self.extension)):
            raise exception.EntityNotFound(entity='neutron extension',
                                           name=self.extension)
        neutron_plugin.find_resourceid_by_name_or_id(
            self.resource_name, value, cmd_resource=self.cmd_resource)


class PortConstraint(NeutronConstraint):
    resource_name = 'port'


class RouterConstraint(NeutronConstraint):
    resource_name = 'router'


class SubnetConstraint(NeutronConstraint):
    resource_name = 'subnet'


class SubnetPoolConstraint(NeutronConstraint):
    resource_name = 'subnetpool'


class AddressScopeConstraint(NeutronConstraint):
    resource_name = 'address_scope'
    extension = 'address-scope'


class QoSPolicyConstraint(NeutronConstraint):
    resource_name = 'policy'
    cmd_resource = 'qos_policy'
    extension = 'qos'
