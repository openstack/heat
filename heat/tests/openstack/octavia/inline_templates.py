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
