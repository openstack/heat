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
from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _

from heat.common.exception import StackValidationFailed

logger = logging.getLogger(__name__)

PARAMETER_GROUPS = 'parameter_groups'
PARAMETERS = 'parameters'


class ParameterGroups(object):
    '''
    The ParameterGroups specified by the stack's template.
    '''
    def __init__(self, tmpl):
        self.tmpl = tmpl
        self.parameters = tmpl.parameters(None, {})
        logger.debug(self.tmpl)
        logger.debug(self.parameters)
        self.parameter_names = []
        if self.parameters:
            self.parameter_names = [param for param in self.parameters]
        self.parameter_groups = tmpl.get(PARAMETER_GROUPS)

    def validate(self):
        '''
        Validate that a parameter belongs to only one Parameter Group
        and that each parameter name references a valid parameter.
        '''
        logger.debug(_('Validating Parameter Groups.'))
        logger.debug(self.parameter_names)
        if self.parameter_groups is not None:
            #Loop through groups and validate parameters
            grouped_parameters = []
            for group in self.parameter_groups:
                parameters = group.get(PARAMETERS)

                if parameters is None:
                    raise StackValidationFailed(message=_(
                        'Parameters must be provided for '
                        'each Parameter Group.'))

                for param in parameters:
                    #Check if param has been added to a previous group
                    if param in grouped_parameters:
                        raise StackValidationFailed(message=_(
                            'The %s parameter must be assigned to one '
                            'Parameter Group only.') % param)
                    else:
                        grouped_parameters.append(param)

                    #Check that grouped parameter references a valid Parameter
                    if param not in self.parameter_names:
                        raise StackValidationFailed(message=_(
                            'The Parameter name (%s) does not reference '
                            'an existing parameter.') % param)
