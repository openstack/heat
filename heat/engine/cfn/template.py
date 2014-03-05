# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

from heat.engine import parameters
from heat.engine import template


class CfnTemplate(template.Template):
    '''A stack template.'''

    SECTIONS = (VERSION, DESCRIPTION, MAPPINGS,
                PARAMETERS, RESOURCES, OUTPUTS) = \
               ('AWSTemplateFormatVersion', 'Description', 'Mappings',
                'Parameters', 'Resources', 'Outputs')

    SECTIONS_NO_DIRECT_ACCESS = set([PARAMETERS, VERSION])

    def __init__(self, template, *args, **kwargs):
        super(CfnTemplate, self).__init__(template, *args, **kwargs)
        self.version = self._version()

    def __getitem__(self, section):
        '''Get the relevant section in the template.'''
        if section not in self.SECTIONS:
            raise KeyError(_('"%s" is not a valid template section') % section)
        if section in self.SECTIONS_NO_DIRECT_ACCESS:
            raise KeyError(
                _('Section %s can not be accessed directly.') % section)

        if section == self.DESCRIPTION:
            default = 'No description'
        else:
            default = {}

        return self.t.get(section, default)

    def _version(self):
        for key in ('HeatTemplateFormatVersion', 'AWSTemplateFormatVersion'):
            if key in self.t:
                return key, self.t[key]

        # All user templates are forced to include a version string. This is
        # just a convenient default for unit tests.
        return 'HeatTemplateFormatVersion', '2012-12-12'

    def param_schemata(self):
        params = self.t.get(self.PARAMETERS, {}).iteritems()
        return dict((name, parameters.Schema.from_dict(schema))
                    for name, schema in params)

    def parameters(self, stack_identifier, user_params, validate_value=True,
                   context=None):
        return parameters.Parameters(stack_identifier, self,
                                     user_params=user_params,
                                     validate_value=validate_value,
                                     context=context)
