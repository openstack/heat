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
from heat.common import identifier
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.aws.cfn import wait_condition_handle as aws_wch
from heat.engine.resources.openstack.heat import wait_condition as heat_wc
from heat.engine import support


class WaitCondition(heat_wc.HeatWaitCondition):

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        HANDLE, TIMEOUT, COUNT,
    ) = (
        'Handle', 'Timeout', 'Count',
    )

    ATTRIBUTES = (
        DATA,
    ) = (
        'Data',
    )

    properties_schema = {
        HANDLE: properties.Schema(
            properties.Schema.STRING,
            _('A reference to the wait condition handle used to signal this '
              'wait condition.'),
            required=True
        ),
        TIMEOUT: properties.Schema(
            properties.Schema.INTEGER,
            _('The number of seconds to wait for the correct number of '
              'signals to arrive.'),
            required=True,
            constraints=[
                constraints.Range(1, 43200),
            ]
        ),
        COUNT: properties.Schema(
            properties.Schema.INTEGER,
            _('The number of success signals that must be received before '
              'the stack creation process continues.'),
            constraints=[
                constraints.Range(min=1),
            ],
            default=1,
            update_allowed=True
        ),
    }

    attributes_schema = {
        DATA: attributes.Schema(
            _('JSON string containing data associated with wait '
              'condition signals sent to the handle.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
    }

    def _validate_handle_url(self):
        handle_url = self.properties[self.HANDLE]
        handle_id = identifier.ResourceIdentifier.from_arn_url(handle_url)
        if handle_id.tenant != self.stack.context.tenant_id:
            raise ValueError(_("WaitCondition invalid Handle tenant %s") %
                             handle_id.tenant)
        if handle_id.stack_name != self.stack.name:
            raise ValueError(_("WaitCondition invalid Handle stack %s") %
                             handle_id.stack_name)
        if handle_id.stack_id != self.stack.id:
            raise ValueError(_("WaitCondition invalid Handle stack %s") %
                             handle_id.stack_id)
        if handle_id.resource_name not in self.stack:
            raise ValueError(_("WaitCondition invalid Handle %s") %
                             handle_id.resource_name)
        if not isinstance(self.stack[handle_id.resource_name],
                          aws_wch.WaitConditionHandle):
            raise ValueError(_("WaitCondition invalid Handle %s") %
                             handle_id.resource_name)

    def handle_create(self):
        self._validate_handle_url()
        return super(WaitCondition, self).handle_create()


def resource_mapping():
    return {
        'AWS::CloudFormation::WaitCondition': WaitCondition,
    }
