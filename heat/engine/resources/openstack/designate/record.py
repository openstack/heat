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


class DesignateRecord(none_resource.NoneResource):
    """Heat Template Resource for Designate Record.

    Designate provides DNS-as-a-Service services for OpenStack. Record is
    storage unit in DNS. So, DNS name server is a server that stores the DNS
    records for a domain. Each record has a type and type-specific data.
    """

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='10.0.0',
        message=_('This resource has been removed, use '
                  'OS::Designate::RecordSet instead.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            version='8.0.0',
            previous_status=support.SupportStatus(version='5.0.0')))


def resource_mapping():
    return {
        'OS::Designate::Record': DesignateRecord
    }
