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


from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource

from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class LaunchConfiguration(resource.Resource):

    PROPERTIES = (
        IMAGE_ID, INSTANCE_TYPE, KEY_NAME, USER_DATA, SECURITY_GROUPS,
        KERNEL_ID, RAM_DISK_ID, BLOCK_DEVICE_MAPPINGS, NOVA_SCHEDULER_HINTS,
    ) = (
        'ImageId', 'InstanceType', 'KeyName', 'UserData', 'SecurityGroups',
        'KernelId', 'RamDiskId', 'BlockDeviceMappings', 'NovaSchedulerHints',
    )

    _NOVA_SCHEDULER_HINT_KEYS = (
        NOVA_SCHEDULER_HINT_KEY, NOVA_SCHEDULER_HINT_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        IMAGE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Glance image ID or name.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('glance.image')
            ]
        ),
        INSTANCE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Nova instance type (flavor).'),
            required=True
        ),
        KEY_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Optional Nova keypair name.'),
            constraints=[
                constraints.CustomConstraint("nova.keypair")
            ]
        ),
        USER_DATA: properties.Schema(
            properties.Schema.STRING,
            _('User data to pass to instance.')
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('Security group names to assign.')
        ),
        KERNEL_ID: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        RAM_DISK_ID: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        BLOCK_DEVICE_MAPPINGS: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        NOVA_SCHEDULER_HINTS: properties.Schema(
            properties.Schema.LIST,
            _('Scheduler hints to pass to Nova (Heat extension).'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    NOVA_SCHEDULER_HINT_KEY: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    NOVA_SCHEDULER_HINT_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
            )
        ),
    }

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if 'Metadata' in tmpl_diff:
            raise resource.UpdateReplace(self.name)

    def FnGetRefId(self):
        return self.physical_resource_name_or_FnGetRefId()


def resource_mapping():
    return {
        'AWS::AutoScaling::LaunchConfiguration': LaunchConfiguration,
    }
