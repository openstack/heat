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

import collections
import six

from heat.common.i18n import _
from heat.engine.cfn import functions as cfn_funcs
from heat.engine.cfn import template as cfn_template
from heat.engine import function
from heat.engine.hot import functions as hot_funcs
from heat.engine.hot import parameters
from heat.engine import rsrc_defn
from heat.engine import template


_RESOURCE_KEYS = (
    RES_TYPE, RES_PROPERTIES, RES_METADATA, RES_DEPENDS_ON,
    RES_DELETION_POLICY, RES_UPDATE_POLICY,
) = (
    'type', 'properties', 'metadata', 'depends_on',
    'deletion_policy', 'update_policy',
)


class HOTemplate20130523(template.Template):
    """
    A Heat Orchestration Template format stack template.
    """

    SECTIONS = (VERSION, DESCRIPTION, PARAMETER_GROUPS, PARAMETERS,
                RESOURCES, OUTPUTS, MAPPINGS) = \
               ('heat_template_version', 'description', 'parameter_groups',
                'parameters', 'resources', 'outputs', '__undefined__')

    SECTIONS_NO_DIRECT_ACCESS = set([PARAMETERS, VERSION])

    _CFN_TO_HOT_SECTIONS = {cfn_template.CfnTemplate.VERSION: VERSION,
                            cfn_template.CfnTemplate.DESCRIPTION: DESCRIPTION,
                            cfn_template.CfnTemplate.PARAMETERS: PARAMETERS,
                            cfn_template.CfnTemplate.MAPPINGS: MAPPINGS,
                            cfn_template.CfnTemplate.RESOURCES: RESOURCES,
                            cfn_template.CfnTemplate.OUTPUTS: OUTPUTS}

    functions = {
        'Fn::GetAZs': cfn_funcs.GetAZs,
        'get_param': hot_funcs.GetParam,
        'get_resource': cfn_funcs.ResourceRef,
        'Ref': cfn_funcs.Ref,
        'get_attr': hot_funcs.GetAttThenSelect,
        'Fn::Select': cfn_funcs.Select,
        'Fn::Join': cfn_funcs.Join,
        'list_join': hot_funcs.Join,
        'Fn::Split': cfn_funcs.Split,
        'str_replace': hot_funcs.Replace,
        'Fn::Replace': cfn_funcs.Replace,
        'Fn::Base64': cfn_funcs.Base64,
        'Fn::MemberListToMap': cfn_funcs.MemberListToMap,
        'resource_facade': hot_funcs.ResourceFacade,
        'Fn::ResourceFacade': cfn_funcs.ResourceFacade,
        'get_file': hot_funcs.GetFile,
    }

    def __getitem__(self, section):
        """"Get the relevant section in the template."""
        #first translate from CFN into HOT terminology if necessary
        if section not in self.SECTIONS:
            section = HOTemplate20130523._translate(
                section, self._CFN_TO_HOT_SECTIONS,
                _('"%s" is not a valid template section'))

        if section not in self.SECTIONS:
            raise KeyError(_('"%s" is not a valid template section') % section)
        if section in self.SECTIONS_NO_DIRECT_ACCESS:
            raise KeyError(
                _('Section %s can not be accessed directly.') % section)

        if section == self.MAPPINGS:
            return {}

        if section == self.DESCRIPTION:
            default = 'No description'
        else:
            default = {}

        # if a section is None (empty yaml section) return {}
        # to be consistent with an empty json section.
        the_section = self.t.get(section) or default

        # In some cases (e.g. parameters), also translate each entry of
        # a section into CFN format (case, naming, etc) so the rest of the
        # engine can cope with it.
        # This is a shortcut for now and might be changed in the future.
        if section == self.RESOURCES:
            return self._translate_resources(the_section)

        if section == self.OUTPUTS:
            return self._translate_outputs(the_section)

        return the_section

    @staticmethod
    def _translate(value, mapping, err_msg=None):
        try:
            return mapping[value]
        except KeyError as ke:
            if err_msg:
                raise KeyError(err_msg % value)
            else:
                raise ke

    def _translate_resources(self, resources):
        """Get the resources of the template translated into CFN format."""
        HOT_TO_CFN_ATTRS = {'type': 'Type',
                            'properties': 'Properties',
                            'metadata': 'Metadata',
                            'depends_on': 'DependsOn',
                            'deletion_policy': 'DeletionPolicy',
                            'update_policy': 'UpdatePolicy'}

        cfn_resources = {}

        for resource_name, attrs in six.iteritems(resources):
            cfn_resource = {}

            for attr, attr_value in six.iteritems(attrs):
                cfn_attr = self._translate(attr, HOT_TO_CFN_ATTRS,
                                           _('"%s" is not a valid keyword '
                                             'inside a resource definition'))
                cfn_resource[cfn_attr] = attr_value

            cfn_resources[resource_name] = cfn_resource

        return cfn_resources

    def _translate_outputs(self, outputs):
        """Get the outputs of the template translated into CFN format."""
        HOT_TO_CFN_ATTRS = {'description': 'Description',
                            'value': 'Value'}

        cfn_outputs = {}

        for output_name, attrs in six.iteritems(outputs):
            cfn_output = {}

            for attr, attr_value in six.iteritems(attrs):
                cfn_attr = self._translate(attr, HOT_TO_CFN_ATTRS,
                                           _('"%s" is not a valid keyword '
                                             'inside an output definition'))
                cfn_output[cfn_attr] = attr_value

            cfn_outputs[output_name] = cfn_output

        return cfn_outputs

    def param_schemata(self):
        parameter_section = self.t.get(self.PARAMETERS)
        if parameter_section is None:
            parameter_section = {}
        params = six.iteritems(parameter_section)
        return dict((name, parameters.HOTParamSchema.from_dict(name, schema))
                    for name, schema in params)

    def parameters(self, stack_identifier, user_params):
        return parameters.HOTParameters(stack_identifier, self,
                                        user_params=user_params)

    def resource_definitions(self, stack):
        allowed_keys = set(_RESOURCE_KEYS)

        def rsrc_defn_item(name, snippet):
            data = self.parse(stack, snippet)

            def get_check_type(key, valid_types, typename, default=None):
                if key in data:
                    field = data[key]
                    if not isinstance(field, valid_types):
                        args = {'name': name, 'key': key, 'typename': typename}
                        msg = _('Resource %(name)s %(key)s type'
                                'must be %(typename)s') % args
                        raise TypeError(msg)
                    return field
                else:
                    return default

            resource_type = get_check_type(RES_TYPE, basestring, 'string')
            if resource_type is None:
                args = {'name': name, 'type_key': RES_TYPE}
                msg = _('Resource %(name)s is missing "%(type_key)s"') % args
                raise KeyError(msg)

            properties = get_check_type(RES_PROPERTIES,
                                        (collections.Mapping,
                                         function.Function),
                                        'object')

            metadata = get_check_type(RES_METADATA,
                                      (collections.Mapping,
                                       function.Function),
                                      'object')

            depends = get_check_type(RES_DEPENDS_ON,
                                     collections.Sequence,
                                     'list or string',
                                     default=[])
            if isinstance(depends, basestring):
                depends = [depends]

            deletion_policy = get_check_type(RES_DELETION_POLICY,
                                             basestring,
                                             'string')

            update_policy = get_check_type(RES_UPDATE_POLICY,
                                           (collections.Mapping,
                                            function.Function),
                                           'object')

            for key in data:
                if key not in allowed_keys:
                    raise ValueError(_('"%s" is not a valid keyword '
                                       'inside a resource definition') % key)

            defn = rsrc_defn.ResourceDefinition(name, resource_type,
                                                properties, metadata,
                                                depends,
                                                deletion_policy,
                                                update_policy)
            return name, defn

        resources = self.t.get(self.RESOURCES) or {}
        return dict(rsrc_defn_item(name, data)
                    for name, data in resources.items())

    def add_resource(self, definition, name=None):
        if name is None:
            name = definition.name

        if self.t.get(self.RESOURCES) is None:
            self.t[self.RESOURCES] = {}
        self.t[self.RESOURCES][name] = definition.render_hot()


class HOTemplate20141016(HOTemplate20130523):
    functions = {
        'get_attr': hot_funcs.GetAtt,
        'get_file': hot_funcs.GetFile,
        'get_param': hot_funcs.GetParam,
        'get_resource': cfn_funcs.ResourceRef,
        'list_join': hot_funcs.Join,
        'resource_facade': hot_funcs.ResourceFacade,
        'str_replace': hot_funcs.Replace,

        'Fn::Select': cfn_funcs.Select,

        # functions removed from 20130523
        'Fn::GetAZs': hot_funcs.Removed,
        'Fn::Join': hot_funcs.Removed,
        'Fn::Split': hot_funcs.Removed,
        'Fn::Replace': hot_funcs.Removed,
        'Fn::Base64': hot_funcs.Removed,
        'Fn::MemberListToMap': hot_funcs.Removed,
        'Fn::ResourceFacade': hot_funcs.Removed,
        'Ref': hot_funcs.Removed,
    }
