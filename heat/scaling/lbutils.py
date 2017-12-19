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

import copy

from heat.common import exception
from heat.common.i18n import _
from heat.engine import scheduler


def reconfigure_loadbalancers(load_balancers, id_list):
    """Notify the LoadBalancer to reload its config.

    This must be done after activation (instance in ACTIVE state), otherwise
    the instances' IP addresses may not be available.
    """
    for lb in load_balancers:
        existing_defn = lb.frozen_definition()
        props = copy.copy(existing_defn.properties(lb.properties_schema,
                                                   lb.context).data)
        if 'Instances' in lb.properties_schema:
            props['Instances'] = id_list
        elif 'members' in lb.properties_schema:
            props['members'] = id_list
        else:
            raise exception.Error(
                _("Unsupported resource '%s' in LoadBalancerNames") % lb.name)

        lb_defn = existing_defn.freeze(properties=props)

        scheduler.TaskRunner(lb.update, lb_defn)()
