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

SPOOL_TEMPLATE = '''
heat_template_version: 2015-04-30
description: Template to test subnetpool Neutron resource
resources:
  sub_pool:
    type: OS::Neutron::SubnetPool
    properties:
      name: the_sp
      prefixes:
        - 10.1.0.0/16
      address_scope: test
      default_quota: 2
      default_prefixlen: 28
      min_prefixlen: 8
      max_prefixlen: 32
      is_default: False
      tenant_id: c1210485b2424d48804aad5d39c61b8f
      shared: False
'''

SPOOL_MINIMAL_TEMPLATE = '''
heat_template_version: 2015-04-30
description: Template to test subnetpool Neutron resource
resources:
  sub_pool:
    type: OS::Neutron::SubnetPool
    properties:
      prefixes:
        - 10.0.0.0/16
        - 10.1.0.0/16
'''

RBAC_TEMPLATE = '''
heat_template_version: 2016-04-08
description: Template to test rbac-policy Neutron resource
resources:
  rbac:
    type: OS::Neutron::RBACPolicy
    properties:
      object_type: network
      target_tenant: d1dbbed707e5469da9cd4fdd618e9706
      action: access_as_shared
      object_id: 9ba4c03a-dbd5-4836-b651-defa595796ba
'''

RBAC_REFERENCE_TEMPLATE = '''
heat_template_version: 2016-04-08
description: Template to test rbac-policy Neutron resource
resources:
  rbac:
    type: OS::Neutron::RBACPolicy
    properties:
      object_type: network
      target_tenant: d1dbbed707e5469da9cd4fdd618e9706
      action: access_as_shared
      object_id: {get_resource: my_net}
  my_net:
    type: OS::Neutron::Net
'''

SECURITY_GROUP_RULE_TEMPLATE = '''
heat_template_version: 2016-10-14
resources:
  security_group_rule:
    type: OS::Neutron::SecurityGroupRule
    properties:
      security_group: 123
      description: test description
      remote_group: 123
      protocol: tcp
      port_range_min: 100
'''

SEGMENT_TEMPLATE = '''
heat_template_version: pike
description: Template to test Segment
resources:
  segment:
    type: OS::Neutron::Segment
    properties:
      network: private
      network_type: vxlan
      segmentation_id: 101
'''
