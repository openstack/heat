# Copyright (c) 2014 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from heat.common.i18n import _
from heat.engine.resources.openstack.heat import none_resource
from heat.engine import support


class SaharaNodeGroupTemplate(none_resource.NoneResource):
    """A resource for managing Sahara node group templates.

    A Node Group Template describes a group of nodes within cluster. It
    contains a list of hadoop processes that will be launched on each instance
    in a group. Also a Node Group Template may provide node scoped
    configurations for those processes.
    """

    support_status = support.SupportStatus(
        version='23.0.0',
        status=support.HIDDEN,
        message=_('Sahara project was retired'),
        previous_status=support.SupportStatus(
            version='22.0.0',
            status=support.DEPRECATED,
            message=_('Sahara project was marked inactive'),
            previous_status=support.SupportStatus(
                version='2014.2',
                status=support.SUPPORTED
            )))


class SaharaClusterTemplate(none_resource.NoneResource):
    """A resource for managing Sahara cluster templates.

    A Cluster Template is designed to bring Node Group Templates together to
    form a Cluster. A Cluster Template defines what Node Groups will be
    included and how many instances will be created in each. Some data
    processing framework configurations can not be applied to a single node,
    but to a whole Cluster. A user can specify these kinds of configurations in
    a Cluster Template. Sahara enables users to specify which processes should
    be added to an anti-affinity group within a Cluster Template. If a process
    is included into an anti-affinity group, it means that VMs where this
    process is going to be launched should be scheduled to different hardware
    hosts.
    """

    support_status = support.SupportStatus(
        version='23.0.0',
        status=support.HIDDEN,
        previous_status=support.SupportStatus(
            version='22.0.0',
            status=support.DEPRECATED,
            message=_('Sahara project was marked inactive'),
            previous_status=support.SupportStatus(
                version='2014.2',
                status=support.SUPPORTED
            )))


def resource_mapping():
    return {
        'OS::Sahara::NodeGroupTemplate': SaharaNodeGroupTemplate,
        'OS::Sahara::ClusterTemplate': SaharaClusterTemplate,
    }
