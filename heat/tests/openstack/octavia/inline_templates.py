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

LB_TEMPLATE = '''
heat_template_version: 2016-04-08
description: Create a loadbalancer
resources:
  lb:
    type: OS::Octavia::LoadBalancer
    properties:
      name: my_lb
      description: my loadbalancer
      vip_address: 10.0.0.4
      vip_subnet: sub123
      provider: octavia
      tenant_id: 1234
      admin_state_up: True
'''

LISTENER_TEMPLATE = '''
heat_template_version: 2016-04-08
description: Create a listener
resources:
  listener:
    type: OS::Octavia::Listener
    properties:
      protocol_port: 80
      protocol: TCP
      loadbalancer: 123
      default_pool: my_pool
      name: my_listener
      description: my listener
      admin_state_up: True
      default_tls_container_ref: ref
      sni_container_refs:
        - ref1
        - ref2
      connection_limit: -1
      tenant_id: 1234
'''

POOL_TEMPLATE = '''
heat_template_version: 2016-04-08
description: Create a pool
resources:
  pool:
    type: OS::Octavia::Pool
    properties:
      name: my_pool
      description: my pool
      session_persistence:
        type: HTTP_COOKIE
      lb_algorithm: ROUND_ROBIN
      loadbalancer: my_lb
      listener: 123
      protocol: HTTP
      admin_state_up: True
'''

MEMBER_TEMPLATE = '''
heat_template_version: 2016-04-08
description: Create a pool member
resources:
  member:
    type: OS::Octavia::PoolMember
    properties:
      pool: 123
      address: 1.2.3.4
      protocol_port: 80
      weight: 1
      subnet: sub123
      admin_state_up: True
'''

MONITOR_TEMPLATE = '''
heat_template_version: 2016-04-08
description: Create a health monitor
resources:
  monitor:
    type: OS::Octavia::HealthMonitor
    properties:
      admin_state_up: True
      delay: 3
      expected_codes: 200-202
      http_method: HEAD
      max_retries: 5
      pool: 123
      timeout: 10
      type: HTTP
      url_path: /health
'''

L7POLICY_TEMPLATE = '''
heat_template_version: 2016-04-08
description: Template to test L7Policy Neutron resource
resources:
  l7policy:
    type: OS::Octavia::L7Policy
    properties:
      admin_state_up: True
      name: test_l7policy
      description: test l7policy resource
      action: REDIRECT_TO_URL
      redirect_url: http://www.mirantis.com
      listener: 123
      position: 1
'''

L7RULE_TEMPLATE = '''
heat_template_version: 2016-04-08
description: Template to test L7Rule Neutron resource
resources:
  l7rule:
    type: OS::Octavia::L7Rule
    properties:
      admin_state_up: True
      l7policy: 123
      type: HEADER
      compare_type: ENDS_WITH
      key: test_key
      value: test_value
      invert: False
'''
