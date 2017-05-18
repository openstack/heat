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

from heat.engine.clients.os.neutron import neutron_constraints as nc

CLIENT_NAME = 'neutron'


class LoadbalancerConstraint(nc.NeutronConstraint):
    resource_name = 'loadbalancer'
    extension = 'lbaasv2'


class ListenerConstraint(nc.NeutronConstraint):
    resource_name = 'listener'
    extension = 'lbaasv2'


class PoolConstraint(nc.NeutronConstraint):
    # Pool constraint for lbaas v2
    resource_name = 'pool'
    extension = 'lbaasv2'


class LBaasV2ProviderConstraint(nc.ProviderConstraint):
    service_type = 'LOADBALANCERV2'
