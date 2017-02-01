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
from heat.engine import constraints as constr
from heat.engine import parameters


class CfnParameters(parameters.Parameters):
    PSEUDO_PARAMETERS = (
        PARAM_STACK_ID, PARAM_STACK_NAME, PARAM_REGION
    ) = (
        'AWS::StackId', 'AWS::StackName', 'AWS::Region'
    )

    def _pseudo_parameters(self, stack_identifier):
        stack_id = (stack_identifier.arn()
                    if stack_identifier is not None else 'None')
        stack_name = stack_identifier and stack_identifier.stack_name

        yield parameters.Parameter(
            self.PARAM_STACK_ID,
            parameters.Schema(parameters.Schema.STRING, _('Stack ID'),
                              default=str(stack_id)))
        if stack_name:
            yield parameters.Parameter(
                self.PARAM_STACK_NAME,
                parameters.Schema(parameters.Schema.STRING, _('Stack Name'),
                                  default=stack_name))
            yield parameters.Parameter(
                self.PARAM_REGION,
                parameters.Schema(parameters.Schema.STRING,
                                  default='ap-southeast-1',
                                  constraints=[
                                      constr.AllowedValues(
                                          ['us-east-1',
                                           'us-west-1',
                                           'us-west-2',
                                           'sa-east-1',
                                           'eu-west-1',
                                           'ap-southeast-1',
                                           'ap-northeast-1'])]))
