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

from heat.common.i18n import _
from heat.engine.resources.openstack.heat import none_resource
from heat.engine import support


class FlowClassifier(none_resource.NoneResource):
    """"Heat Template Resource for networking-sfc flow-classifier.

    This resource used to select the traffic that can access the service chain.
    Traffic that matches any flow classifier will be directed to the first
    port in the chain.
    """

    support_status = support.SupportStatus(
        version='28.0.0',
        status=support.HIDDEN,
        message=_('networking-sfc is deprecated'),
        previous_status=support.SupportStatus(
            version='8.0.0',
            status=support.UNSUPPORTED))


def resource_mapping():
    return {
        'OS::Neutron::FlowClassifier': FlowClassifier,
    }
