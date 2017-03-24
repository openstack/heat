# Copyright 2014 Mirantis Inc.
# All Rights Reserved.
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

"""Sample plugin for Heat.

For more Heat related benchmarks take a look here:
https://git.openstack.org/cgit/openstack/rally/tree/rally/plugins/openstack/scenarios/heat

About plugins: https://rally.readthedocs.io/en/latest/plugins/#rally-plugins

Rally concepts https://wiki.openstack.org/wiki/Rally/Concepts
"""


from rally.plugins.openstack import scenario


class HeatPlugin(scenario.OpenStackScenario):

    @scenario.configure(context={"cleanup": ["heat"]})
    def list_benchmark(self, container_format,
                            image_location, disk_format, **kwargs):
        """Get heatclient and do whatever."""
        stacks = list(self.clients("heat").stacks.list())
