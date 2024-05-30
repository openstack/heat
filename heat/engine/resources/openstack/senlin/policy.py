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
#

from heat.engine.resources.openstack.senlin import res_base


class Policy(res_base.BaseSenlinResource):
    """A resource that creates a Senlin Policy.

    A policy is a set of rules that can be checked and/or enforced when
    an action is performed on a Cluster.
    """
    pass


def resource_mapping():
    return {
        'OS::Senlin::Policy': Policy
    }
