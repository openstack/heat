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

from oslo_log import log as logging

from heat.common import exception
from heat.common.i18n import _

LOG = logging.getLogger(__name__)

PARAMETER_GROUPS = 'parameter_groups'
PARAMETERS = 'parameters'


class ParameterGroups(object):
    """The ParameterGroups specified by the stack's template."""
    def __init__(self, tmpl):
        self.tmpl = tmpl
        self.parameters = tmpl.parameters(None, {}, param_defaults={})
        self.parameter_names = []
        if self.parameters:
            self.parameter_names = [param for param in self.parameters]
        self.parameter_groups = tmpl.get(PARAMETER_GROUPS)

    def validate(self):
        """Validate the parameter group.

        Validate that each parameter belongs to only one Parameter Group and
        that each parameter name in the group references a valid parameter.
        """
        LOG.debug('Validating Parameter Groups: %s',
                  ', '.join(self.parameter_names))
        if self.parameter_groups:
            if not isinstance(self.parameter_groups, list):
                raise exception.StackValidationFailed(
                    error=_('Parameter Groups error'),
                    path=[PARAMETER_GROUPS],
                    message=_('The %s should be a list.') % PARAMETER_GROUPS)

            # Loop through groups and validate parameters
            grouped_parameters = []
            for group in self.parameter_groups:
                parameters = group.get(PARAMETERS)
                if parameters is None:
                    raise exception.StackValidationFailed(
                        error=_('Parameter Groups error'),
                        path=[PARAMETER_GROUPS, group.get('label', '')],
                        message=_('The %s must be provided for '
                                  'each parameter group.') % PARAMETERS)

                if not isinstance(parameters, list):
                    raise exception.StackValidationFailed(
                        error=_('Parameter Groups error'),
                        path=[PARAMETER_GROUPS, group.get('label', '')],
                        message=_('The %s of parameter group '
                                  'should be a list.') % PARAMETERS)

                for param in parameters:
                    # Check if param has been added to a previous group
                    if param in grouped_parameters:
                        raise exception.StackValidationFailed(
                            error=_('Parameter Groups error'),
                            path=[PARAMETER_GROUPS, group.get('label', '')],
                            message=_(
                                'The %s parameter must be assigned to one '
                                'parameter group only.') % param)
                    else:
                        grouped_parameters.append(param)

                    # Check that grouped parameter references a valid Parameter
                    if param not in self.parameter_names:
                        raise exception.StackValidationFailed(
                            error=_('Parameter Groups error'),
                            path=[PARAMETER_GROUPS, group.get('label', '')],
                            message=_(
                                'The grouped parameter %s does not reference '
                                'a valid parameter.') % param)
