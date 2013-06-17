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

from heat.common import exception
from heat.engine import template
from heat.openstack.common import log as logging


logger = logging.getLogger(__name__)

SECTIONS = (VERSION, DESCRIPTION, PARAMETERS,
            RESOURCES, OUTPUTS, UNDEFINED) = \
           ('heat_template_version', 'description', 'parameters',
            'resources', 'outputs', '__undefined__')

_CFN_TO_HOT_SECTIONS = {template.VERSION: VERSION,
                        template.DESCRIPTION: DESCRIPTION,
                        template.PARAMETERS: PARAMETERS,
                        template.MAPPINGS: UNDEFINED,
                        template.RESOURCES: RESOURCES,
                        template.OUTPUTS: OUTPUTS}


class HOTemplate(template.Template):
    """
    A Heat Orchestration Template format stack template.
    """

    def __getitem__(self, section):
        """"Get the relevant section in the template."""
        #first translate from CFN into HOT terminology if necessary
        section = HOTemplate._translate(section, _CFN_TO_HOT_SECTIONS, section)

        if section not in SECTIONS:
            raise KeyError('"%s" is not a valid template section' % section)

        if section == VERSION:
            return self.t[section]

        if section == UNDEFINED:
            return {}

        if section == DESCRIPTION:
            default = 'No description'
        else:
            default = {}

        the_section = self.t.get(section, default)

        # In some cases (e.g. parameters), also translate each entry of
        # a section into CFN format (case, naming, etc) so the rest of the
        # engine can cope with it.
        # This is a shortcut for now and might be changed in the future.

        if section == PARAMETERS:
            return self._translate_parameters(the_section)

        if section == RESOURCES:
            return self._translate_resources(the_section)

        if section == OUTPUTS:
            return self._translate_outputs(the_section)

        return the_section

    @staticmethod
    def _translate(value, mapping, default=None):
        if value in mapping:
            return mapping[value]

        return default

    def _translate_parameters(self, parameters):
        """Get the parameters of the template translated into CFN format."""
        HOT_TO_CFN_ATTRS = {'type': 'Type',
                            'description': 'Description'}

        HOT_TO_CFN_TYPES = {'string': 'String'}

        cfn_params = {}

        for param_name, attrs in parameters.iteritems():
            cfn_param = {}

            for attr, attr_value in attrs.iteritems():
                cfn_attr = self._translate(attr, HOT_TO_CFN_ATTRS, attr)

                if attr == 'type':
                    # try to translate type; if no translation found, keep
                    # original value and let engine throw an error for an
                    # unsupported type
                    attr_value = self._translate(attr_value, HOT_TO_CFN_TYPES,
                                                 attr_value)

                cfn_param[cfn_attr] = attr_value

            if len(cfn_param) > 0:
                cfn_params[param_name] = cfn_param

        return cfn_params

    def _translate_resources(self, resources):
        """Get the resources of the template translated into CFN format."""
        HOT_TO_CFN_ATTRS = {'type': 'Type',
                            'properties': 'Properties'}

        cfn_resources = {}

        for resource_name, attrs in resources.iteritems():
            cfn_resource = {}

            for attr, attr_value in attrs.iteritems():
                cfn_attr = self._translate(attr, HOT_TO_CFN_ATTRS, attr)
                cfn_resource[cfn_attr] = attr_value

            cfn_resources[resource_name] = cfn_resource

        return cfn_resources

    def _translate_outputs(self, outputs):
        """Get the outputs of the template translated into CFN format."""
        HOT_TO_CFN_ATTRS = {'description': 'Description',
                            'value': 'Value'}

        cfn_outputs = {}

        for output_name, attrs in outputs.iteritems():
            cfn_output = {}

            for attr, attr_value in attrs.iteritems():
                cfn_attr = self._translate(attr, HOT_TO_CFN_ATTRS, attr)
                cfn_output[cfn_attr] = attr_value

            cfn_outputs[output_name] = cfn_output

        return cfn_outputs

    @staticmethod
    def resolve_param_refs(s, parameters):
        """
        Resolve constructs of the form { get_param: my_param }
        """
        def match_param_ref(key, value):
            return (key == 'get_param' and
                    isinstance(value, basestring) and
                    value in parameters)

        def handle_param_ref(ref):
            try:
                return parameters[ref]
            except (KeyError, ValueError):
                raise exception.UserParameterMissing(key=ref)

        return template._resolve(match_param_ref, handle_param_ref, s)

    @staticmethod
    def resolve_attributes(s, resources):
        """
        Resolve constructs of the form { get_attr: [my_resource, my_attr] }
        """
        def match_get_attr(key, value):
            return (key == 'get_attr' and
                    isinstance(value, list) and
                    len(value) == 2 and
                    isinstance(value[0], basestring) and
                    value[0] in resources)

        def handle_get_attr(args):
            resource, att = args
            try:
                r = resources[resource]
                if r.state in (
                        (r.CREATE, r.IN_PROGRESS),
                        (r.CREATE, r.COMPLETE),
                        (r.UPDATE, r.IN_PROGRESS),
                        (r.UPDATE, r.COMPLETE)):
                    return r.FnGetAtt(att)
            except KeyError:
                raise exception.InvalidTemplateAttribute(resource=resource,
                                                         key=att)

        return template._resolve(match_get_attr, handle_get_attr, s)
