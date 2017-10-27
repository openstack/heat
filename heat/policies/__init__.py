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


import itertools

from heat.policies import actions
from heat.policies import base
from heat.policies import build_info
from heat.policies import cloudformation
from heat.policies import events
from heat.policies import resource
from heat.policies import resource_types
from heat.policies import service
from heat.policies import software_configs
from heat.policies import software_deployments
from heat.policies import stacks


def list_rules():
    return itertools.chain(
        base.list_rules(),
        actions.list_rules(),
        build_info.list_rules(),
        cloudformation.list_rules(),
        events.list_rules(),
        resource.list_rules(),
        resource_types.list_rules(),
        service.list_rules(),
        software_configs.list_rules(),
        software_deployments.list_rules(),
        stacks.list_rules(),
    )
