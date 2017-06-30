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

import functools

import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine.cfn import functions as cfn_funcs
from heat.engine.cfn import parameters as cfn_params
from heat.engine import function
from heat.engine import parameters
from heat.engine import rsrc_defn
from heat.engine import template_common


class CfnTemplateBase(template_common.CommonTemplate):
    """The base implementation of cfn template."""

    SECTIONS = (
        VERSION, ALTERNATE_VERSION,
        DESCRIPTION, MAPPINGS, PARAMETERS, RESOURCES, OUTPUTS,
    ) = (
        'AWSTemplateFormatVersion', 'HeatTemplateFormatVersion',
        'Description', 'Mappings', 'Parameters', 'Resources', 'Outputs',
    )

    OUTPUT_KEYS = (
        OUTPUT_DESCRIPTION, OUTPUT_VALUE,
    ) = (
        'Description', 'Value',
    )

    SECTIONS_NO_DIRECT_ACCESS = set([PARAMETERS, VERSION, ALTERNATE_VERSION])

    _RESOURCE_KEYS = (
        RES_TYPE, RES_PROPERTIES, RES_METADATA, RES_DEPENDS_ON,
        RES_DELETION_POLICY, RES_UPDATE_POLICY, RES_DESCRIPTION,
    ) = (
        'Type', 'Properties', 'Metadata', 'DependsOn',
        'DeletionPolicy', 'UpdatePolicy', 'Description',
    )

    functions = {
        'Fn::FindInMap': cfn_funcs.FindInMap,
        'Fn::GetAZs': cfn_funcs.GetAZs,
        'Ref': cfn_funcs.Ref,
        'Fn::GetAtt': cfn_funcs.GetAtt,
        'Fn::Select': cfn_funcs.Select,
        'Fn::Join': cfn_funcs.Join,
        'Fn::Base64': cfn_funcs.Base64,
    }

    deletion_policies = {
        'Delete': rsrc_defn.ResourceDefinition.DELETE,
        'Retain': rsrc_defn.ResourceDefinition.RETAIN,
        'Snapshot': rsrc_defn.ResourceDefinition.SNAPSHOT
    }

    HOT_TO_CFN_RES_ATTRS = {'type': RES_TYPE,
                            'properties': RES_PROPERTIES,
                            'metadata': RES_METADATA,
                            'depends_on': RES_DEPENDS_ON,
                            'deletion_policy': RES_DELETION_POLICY,
                            'update_policy': RES_UPDATE_POLICY}

    HOT_TO_CFN_OUTPUT_ATTRS = {'description': OUTPUT_DESCRIPTION,
                               'value': OUTPUT_VALUE}

    def __getitem__(self, section):
        """Get the relevant section in the template."""
        if section not in self.SECTIONS:
            raise KeyError(_('"%s" is not a valid template section') % section)
        if section in self.SECTIONS_NO_DIRECT_ACCESS:
            raise KeyError(
                _('Section %s can not be accessed directly.') % section)

        if section == self.DESCRIPTION:
            default = 'No description'
        else:
            default = {}

        # if a section is None (empty yaml section) return {}
        # to be consistent with an empty json section.
        return self.t.get(section) or default

    def param_schemata(self, param_defaults=None):
        params = self.t.get(self.PARAMETERS) or {}
        pdefaults = param_defaults or {}
        for name, schema in six.iteritems(params):
            if name in pdefaults:
                params[name][parameters.DEFAULT] = pdefaults[name]

        return dict((name, parameters.Schema.from_dict(name, schema))
                    for name, schema in six.iteritems(params))

    def get_section_name(self, section):
        return section

    def parameters(self, stack_identifier, user_params, param_defaults=None):
        return cfn_params.CfnParameters(stack_identifier, self,
                                        user_params=user_params,
                                        param_defaults=param_defaults)

    def resource_definitions(self, stack):
        resources = self.t.get(self.RESOURCES) or {}

        conditions = self.conditions(stack)

        def defns():
            for name, snippet in resources.items():
                try:
                    defn_data = dict(self._rsrc_defn_args(stack, name,
                                                          snippet))
                except (TypeError, ValueError, KeyError) as ex:
                    msg = six.text_type(ex)
                    raise exception.StackValidationFailed(message=msg)

                defn = rsrc_defn.ResourceDefinition(name, **defn_data)
                cond_name = defn.condition()

                if cond_name is not None:
                    try:
                        enabled = conditions.is_enabled(cond_name)
                    except ValueError as exc:
                        path = [self.RESOURCES, name, self.RES_CONDITION]
                        message = six.text_type(exc)
                        raise exception.StackValidationFailed(path=path,
                                                              message=message)
                    if not enabled:
                        continue

                yield name, defn

        return dict(defns())

    def add_resource(self, definition, name=None):
        if name is None:
            name = definition.name
        hot_tmpl = definition.render_hot()

        if self.t.get(self.RESOURCES) is None:
            self.t[self.RESOURCES] = {}

        cfn_tmpl = dict((self.HOT_TO_CFN_RES_ATTRS[k], v)
                        for k, v in hot_tmpl.items())

        dep_list = cfn_tmpl.get(self.RES_DEPENDS_ON, [])
        if len(dep_list) == 1:
            dep_res = cfn_tmpl[self.RES_DEPENDS_ON][0]
            if dep_res in self.t[self.RESOURCES]:
                cfn_tmpl[self.RES_DEPENDS_ON] = dep_res
            else:
                del cfn_tmpl[self.RES_DEPENDS_ON]
        elif dep_list:
            cfn_tmpl[self.RES_DEPENDS_ON] = [d for d in dep_list
                                             if d in self.t[self.RESOURCES]]

        self.t[self.RESOURCES][name] = cfn_tmpl

    def add_output(self, definition):
        hot_op = definition.render_hot()
        cfn_op = dict((self.HOT_TO_CFN_OUTPUT_ATTRS[k], v)
                      for k, v in hot_op.items())

        if self.t.get(self.OUTPUTS) is None:
            self.t[self.OUTPUTS] = {}
        self.t[self.OUTPUTS][definition.name] = cfn_op


class CfnTemplate(CfnTemplateBase):

    CONDITIONS = 'Conditions'
    SECTIONS = CfnTemplateBase.SECTIONS + (CONDITIONS,)
    SECTIONS_NO_DIRECT_ACCESS = (CfnTemplateBase.SECTIONS_NO_DIRECT_ACCESS |
                                 set([CONDITIONS]))

    RES_CONDITION = 'Condition'
    _RESOURCE_KEYS = CfnTemplateBase._RESOURCE_KEYS + (RES_CONDITION,)
    HOT_TO_CFN_RES_ATTRS = CfnTemplateBase.HOT_TO_CFN_RES_ATTRS
    HOT_TO_CFN_RES_ATTRS.update({'condition': RES_CONDITION})

    OUTPUT_CONDITION = 'Condition'
    OUTPUT_KEYS = CfnTemplateBase.OUTPUT_KEYS + (OUTPUT_CONDITION,)

    functions = {
        'Fn::FindInMap': cfn_funcs.FindInMap,
        'Fn::GetAZs': cfn_funcs.GetAZs,
        'Ref': cfn_funcs.Ref,
        'Fn::GetAtt': cfn_funcs.GetAtt,
        'Fn::Select': cfn_funcs.Select,
        'Fn::Join': cfn_funcs.Join,
        'Fn::Split': cfn_funcs.Split,
        'Fn::Replace': cfn_funcs.Replace,
        'Fn::Base64': cfn_funcs.Base64,
        'Fn::MemberListToMap': cfn_funcs.MemberListToMap,
        'Fn::ResourceFacade': cfn_funcs.ResourceFacade,
        'Fn::If': cfn_funcs.If,
    }

    condition_functions = {
        'Fn::Equals': cfn_funcs.Equals,
        'Ref': cfn_funcs.ParamRef,
        'Fn::FindInMap': cfn_funcs.FindInMap,
        'Fn::Not': cfn_funcs.Not,
        'Fn::And': cfn_funcs.And,
        'Fn::Or': cfn_funcs.Or
    }

    def __init__(self, tmpl, template_id=None, files=None, env=None):
        super(CfnTemplate, self).__init__(tmpl, template_id, files, env)

        self.merge_sections = [self.PARAMETERS, self.CONDITIONS]

    def _get_condition_definitions(self):
        return self.t.get(self.CONDITIONS, {})

    def _rsrc_defn_args(self, stack, name, data):
        for arg in super(CfnTemplate, self)._rsrc_defn_args(stack, name, data):
            yield arg

        parse_cond = functools.partial(self.parse_condition, stack)

        yield ('condition',
               self._parse_resource_field(self.RES_CONDITION,
                                          (six.string_types, bool,
                                           function.Function),
                                          'string or boolean',
                                          name, data, parse_cond))


class HeatTemplate(CfnTemplateBase):
    functions = {
        'Fn::FindInMap': cfn_funcs.FindInMap,
        'Fn::GetAZs': cfn_funcs.GetAZs,
        'Ref': cfn_funcs.Ref,
        'Fn::GetAtt': cfn_funcs.GetAtt,
        'Fn::Select': cfn_funcs.Select,
        'Fn::Join': cfn_funcs.Join,
        'Fn::Split': cfn_funcs.Split,
        'Fn::Replace': cfn_funcs.Replace,
        'Fn::Base64': cfn_funcs.Base64,
        'Fn::MemberListToMap': cfn_funcs.MemberListToMap,
        'Fn::ResourceFacade': cfn_funcs.ResourceFacade,
    }
