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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource


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

    _BLOCK_DEVICE_MAPPING_KEYS = (
        DEVICE_NAME, EBS, NO_DEVICE, VIRTUAL_NAME,
    ) = (
        'DeviceName', 'Ebs', 'NoDevice', 'VirtualName',
    )

    _EBS_KEYS = (
        DELETE_ON_TERMINATION, IOPS, SNAPSHOT_ID, VOLUME_SIZE,
        VOLUME_TYPE,
    ) = (
        'DeleteOnTermination', 'Iops', 'SnapshotId', 'VolumeSize',
        'VolumeType'
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
            properties.Schema.LIST,
            _('Block device mappings to attach to instance.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    DEVICE_NAME: properties.Schema(
                        properties.Schema.STRING,
                        _('A device name where the volume will be '
                          'attached in the system at /dev/device_name.'
                          'e.g. vdb'),
                        required=True,
                    ),
                    EBS: properties.Schema(
                        properties.Schema.MAP,
                        _('The ebs volume to attach to the instance.'),
                        schema={
                            DELETE_ON_TERMINATION: properties.Schema(
                                properties.Schema.BOOLEAN,
                                _('Indicate whether the volume should be '
                                  'deleted when the instance is terminated.'),
                                default=True
                            ),
                            IOPS: properties.Schema(
                                properties.Schema.NUMBER,
                                _('The number of I/O operations per second '
                                  'that the volume supports.'),
                                implemented=False
                            ),
                            SNAPSHOT_ID: properties.Schema(
                                properties.Schema.STRING,
                                _('The ID of the snapshot to create '
                                  'a volume from.'),
                            ),
                            VOLUME_SIZE: properties.Schema(
                                properties.Schema.STRING,
                                _('The size of the volume, in GB. Must be '
                                  'equal or greater than the size of the '
                                  'snapshot. It is safe to leave this blank '
                                  'and have the Compute service infer '
                                  'the size.'),
                            ),
                            VOLUME_TYPE: properties.Schema(
                                properties.Schema.STRING,
                                _('The volume type.'),
                                implemented=False
                            ),
                        },
                    ),
                    NO_DEVICE: properties.Schema(
                        properties.Schema.MAP,
                        _('The can be used to unmap a defined device.'),
                        implemented=False
                    ),
                    VIRTUAL_NAME: properties.Schema(
                        properties.Schema.STRING,
                        _('The name of the virtual device. The name must be '
                          'in the form ephemeralX where X is a number '
                          'starting from zero (0); for example, ephemeral0.'),
                        implemented=False
                    ),
                },
            ),
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

    def validate(self):
        '''
        Validate any of the provided params
        '''
        super(LaunchConfiguration, self).validate()
        # now we don't support without snapshot_id in bdm
        bdm = self.properties.get(self.BLOCK_DEVICE_MAPPINGS)
        if bdm:
            for mapping in bdm:
                ebs = mapping.get(self.EBS)
                if ebs:
                    snapshot_id = ebs.get(self.SNAPSHOT_ID)
                    if not snapshot_id:
                        msg = _("SnapshotId is missing, this is required "
                                "when specifying BlockDeviceMappings.")
                        raise exception.StackValidationFailed(message=msg)
                else:
                    msg = _("Ebs is missing, this is required "
                            "when specifying BlockDeviceMappings.")
                    raise exception.StackValidationFailed(message=msg)


def resource_mapping():
    return {
        'AWS::AutoScaling::LaunchConfiguration': LaunchConfiguration,
    }
