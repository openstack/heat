#
#    All Rights Reserved.
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

from neutronclient.common import exceptions
from neutronclient.neutron import v2_0 as neutronV20

from heat.engine import constraints


class LoadbalancerConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.NeutronClientException,)

    def validate_with_client(self, client, value):
        neutron_client = client.client('neutron')
        neutronV20.find_resourceid_by_name_or_id(
            neutron_client, 'loadbalancer', value)


class ListenerConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.NeutronClientException,)

    def validate_with_client(self, client, value):
        neutron_client = client.client('neutron')
        neutronV20.find_resourceid_by_name_or_id(
            neutron_client, 'listener', value)


class PoolConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.NeutronClientException,)

    def validate_with_client(self, client, value):
        neutron_client = client.client('neutron')
        # v2 pool is called lbaas_pool to differentiate from v1 pool
        neutronV20.find_resourceid_by_name_or_id(
            neutron_client, 'lbaas_pool', value)
