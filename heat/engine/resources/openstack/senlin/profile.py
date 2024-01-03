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
#    Copyright 2015 IBM Corp.

from heat.engine.resources.openstack.senlin import res_base


class Profile(res_base.BaseSenlinResource):
    """A resource that creates a Senlin Profile.

    Profile resource in senlin is a template describing how to create nodes in
    cluster.
    """
    pass


def resource_mapping():
    return {
        'OS::Senlin::Profile': Profile
    }
