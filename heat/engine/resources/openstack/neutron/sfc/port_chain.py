# Copyright (c) 2016 Huawei Technologies India Pvt Ltd
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

from heat.common.i18n import _
from heat.engine.resources.openstack.heat import none_resource
from heat.engine import support


class PortChain(none_resource.NoneResource):
    """A resource for neutron networking-sfc.

    This resource used to define the service function path by arranging
    networking-sfc port-pair-groups and set of flow classifiers, to specify
    the classified traffic flows to enter the chain.
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
        'OS::Neutron::PortChain': PortChain,
    }
