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

import six

from heat.common import exception
from heat.common import grouputils
from heat.common.i18n import _
from heat.engine import rsrc_defn
from heat.engine import scheduler


def reload_loadbalancers(group, load_balancers, exclude=None):
    """Notify the LoadBalancer to reload its config.

    This must be done after activation (instance in ACTIVE state), otherwise
    the instances' IP addresses may not be available.
    """
    exclude = exclude or []
    id_list = grouputils.get_member_refids(group, exclude=exclude)
    for name, lb in six.iteritems(load_balancers):
        props = copy.copy(lb.properties.data)
        if 'Instances' in lb.properties_schema:
            props['Instances'] = id_list
        elif 'members' in lb.properties_schema:
            props['members'] = id_list
        else:
            raise exception.Error(
                _("Unsupported resource '%s' in LoadBalancerNames") % name)

        lb_defn = rsrc_defn.ResourceDefinition(
            lb.name,
            lb.type(),
            properties=props,
            metadata=lb.t.metadata(),
            deletion_policy=lb.t.deletion_policy())

        scheduler.TaskRunner(lb.update, lb_defn)()
