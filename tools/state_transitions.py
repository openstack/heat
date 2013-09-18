#!/usr/bin/python

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

"""Generate a list of all possible state transitions.

Useful as a starting point for documentation.
"""

from heat.engine import resource

actions = resource.Resource.ACTIONS
stack_statuses = resource.Resource.STATUSES
engine_statuses = ("Alive", "Dead")

print("""\
| Orig action | Stack status | Engine status | New action | Behavior         |
|-------------+--------------+---------------+------------+------------------|\
""")

for orig_action in actions:
    for stack_status in stack_statuses:
        for new_action in actions:
            if stack_status == resource.Resource.IN_PROGRESS:
                for engine_status in engine_statuses:
                    print("| %11s | %12s | %13s | %10s |                  |" \
                          % (orig_action, stack_status, engine_status,
                          new_action))
            else:
                print("| %11s | %12s | %13s | %10s |                  |" \
                      % (orig_action, stack_status, "NA", new_action))
