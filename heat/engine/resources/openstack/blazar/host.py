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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class Host(resource.Resource):
    """A resource to manage Blazar hosts.

    Host resource manages the physical hosts for the lease/reservation
    within OpenStack.

    # TODO(asmita): Based on an agreement with Blazar team, this resource
    class does not support updating host resource as currently Blazar does
    not support to delete existing extra_capability keys while updating host.
    Also, in near future, when Blazar team will come up with a new alternative
    API to resolve this issue, we will need to modify this class.
    """

    support_status = support.SupportStatus(version='12.0.0')

    PROPERTIES = (
        NAME, EXTRA_CAPABILITY,
    ) = (
        'name', 'extra_capability',
    )

    ATTRIBUTES = (
        HYPERVISOR_HOSTNAME, HYPERVISOR_TYPE,  HYPERVISOR_VERSION,
        VCPUS, CPU_INFO, MEMORY_MB, LOCAL_GB,
        SERVICE_NAME, RESERVABLE, STATUS, TRUST_ID,
        EXTRA_CAPABILITY_ATTR, CREATED_AT, UPDATED_AT,
    ) = (
        'hypervisor_hostname', 'hypervisor_type', 'hypervisor_version',
        'vcpus', 'cpu_info', 'memory_mb', 'local_gb',
        'service_name', 'reservable', 'status', 'trust_id',
        'extra_capability', 'created_at', 'updated_at',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name of the host.'),
            required=True,
        ),
        EXTRA_CAPABILITY: properties.Schema(
            properties.Schema.MAP,
            _('The extra capability of the host.'),
        )
    }

    attributes_schema = {
        HYPERVISOR_HOSTNAME: attributes.Schema(
            _('The hypervisor name of the host.'),
            type=attributes.Schema.STRING,
        ),
        HYPERVISOR_TYPE: attributes.Schema(
            _('The hypervisor type the host.'),
            type=attributes.Schema.STRING,
        ),
        HYPERVISOR_VERSION: attributes.Schema(
            _('The hypervisor version of the host.'),
            type=attributes.Schema.INTEGER,
        ),
        VCPUS: attributes.Schema(
            _('The number of the VCPUs of the host.'),
            type=attributes.Schema.INTEGER,
        ),
        CPU_INFO: attributes.Schema(
            _('Information of the CPU of the host.'),
            type=attributes.Schema.MAP,
        ),
        MEMORY_MB: attributes.Schema(
            _('Megabytes of the memory of the host.'),
            type=attributes.Schema.INTEGER,
        ),
        LOCAL_GB: attributes.Schema(
            _('Gigabytes of the disk of the host.'),
            type=attributes.Schema.INTEGER,
        ),
        SERVICE_NAME: attributes.Schema(
            _('The compute service name of the host.'),
            type=attributes.Schema.STRING,
        ),
        RESERVABLE: attributes.Schema(
            _('The flag which represents whether the host is reservable '
              'or not.'),
            type=attributes.Schema.BOOLEAN,
        ),
        STATUS: attributes.Schema(
            _('The status of the host.'),
            type=attributes.Schema.STRING,
        ),
        TRUST_ID: attributes.Schema(
            _('The UUID of the trust of the host operator.'),
            type=attributes.Schema.STRING,
        ),
        EXTRA_CAPABILITY_ATTR: attributes.Schema(
            _('The extra capability of the host.'),
            type=attributes.Schema.MAP,
        ),
        CREATED_AT: attributes.Schema(
            _('The date and time when the host was created. '
              'The date and time format must be "CCYY-MM-DD hh:mm".'),
            type=attributes.Schema.STRING,
        ),
        UPDATED_AT: attributes.Schema(
            _('The date and time when the host was updated. '
              'The date and time format must be "CCYY-MM-DD hh:mm".'),
            type=attributes.Schema.STRING
        ),
    }

    default_client_name = 'blazar'

    entity = 'host'

    def _parse_extra_capability(self, args):
        if self.NAME in args[self.EXTRA_CAPABILITY]:
            # Remove "name" key if present in the extra_capability property.
            del args[self.EXTRA_CAPABILITY][self.NAME]
        args.update(args[self.EXTRA_CAPABILITY])
        args.pop(self.EXTRA_CAPABILITY)
        return args

    def handle_create(self):
        args = dict((k, v) for k, v in self.properties.items()
                    if v is not None)

        if self.EXTRA_CAPABILITY in args:
            args = self._parse_extra_capability(args)

        host = self.client_plugin().create_host(**args)
        self.resource_id_set(host['id'])

        return host['id']

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        host = self.client_plugin().get_host(self.resource_id)
        try:
            return host[name]
        except KeyError:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=name)


def resource_mapping():
    return {
        'OS::Blazar::Host': Host
    }
