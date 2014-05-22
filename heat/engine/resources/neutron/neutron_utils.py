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

from neutronclient.neutron import v2_0 as neutronV20


def find_neutron_resource(neutron_client, props, key, key_type):
    return neutronV20.find_resourceid_by_name_or_id(
        neutron_client, key_type, props.get(key))


def resolve_network(neutron_client, props, net_key, net_id_key):
    if props.get(net_key):
        props[net_id_key] = find_neutron_resource(
            neutron_client, props, net_key, 'network')
        props.pop(net_key)
    return props[net_id_key]


def resolve_subnet(neutron_client, props, subnet_key, subnet_id_key):
    if props.get(subnet_key):
        props[subnet_id_key] = find_neutron_resource(
            neutron_client, props, subnet_key, 'subnet')
        props.pop(subnet_key)
    return props[subnet_id_key]
