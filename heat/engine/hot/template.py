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
from heat.engine.cfn import template as cfn_template
from heat.engine import function
from heat.engine.hot import functions as hot_funcs
from heat.engine.hot import parameters
from heat.engine import rsrc_defn
from heat.engine import template_common


class HOTemplate20130523(template_common.CommonTemplate):
    """A Heat Orchestration Template format stack template."""

    SECTIONS = (
        VERSION, DESCRIPTION, PARAMETER_GROUPS,
        PARAMETERS, RESOURCES, OUTPUTS, MAPPINGS,
    ) = (
        'heat_template_version', 'description', 'parameter_groups',
        'parameters', 'resources', 'outputs', '__undefined__',
    )

    OUTPUT_KEYS = (
        OUTPUT_DESCRIPTION, OUTPUT_VALUE,
    ) = (
        'description', 'value',
    )

    SECTIONS_NO_DIRECT_ACCESS = set([PARAMETERS, VERSION])

    _CFN_TO_HOT_SECTIONS = {cfn_template.CfnTemplate.VERSION: VERSION,
                            cfn_template.CfnTemplate.DESCRIPTION: DESCRIPTION,
                            cfn_template.CfnTemplate.PARAMETERS: PARAMETERS,
                            cfn_template.CfnTemplate.MAPPINGS: MAPPINGS,
                            cfn_template.CfnTemplate.RESOURCES: RESOURCES,
                            cfn_template.CfnTemplate.OUTPUTS: OUTPUTS}

    _RESOURCE_KEYS = (
        RES_TYPE, RES_PROPERTIES, RES_METADATA, RES_DEPENDS_ON,
        RES_DELETION_POLICY, RES_UPDATE_POLICY, RES_DESCRIPTION,
    ) = (
        'type', 'properties', 'metadata', 'depends_on',
        'deletion_policy', 'update_policy', 'description',
    )

    _RESOURCE_HOT_TO_CFN_ATTRS = {
        RES_TYPE: cfn_template.CfnTemplate.RES_TYPE,
        RES_PROPERTIES: cfn_template.CfnTemplate.RES_PROPERTIES,
        RES_METADATA: cfn_template.CfnTemplate.RES_METADATA,
        RES_DEPENDS_ON: cfn_template.CfnTemplate.RES_DEPENDS_ON,
        RES_DELETION_POLICY: cfn_template.CfnTemplate.RES_DELETION_POLICY,
        RES_UPDATE_POLICY: cfn_template.CfnTemplate.RES_UPDATE_POLICY,
        RES_DESCRIPTION: cfn_template.CfnTemplate.RES_DESCRIPTION}

    _HOT_TO_CFN_ATTRS = _RESOURCE_HOT_TO_CFN_ATTRS
    _HOT_TO_CFN_ATTRS.update(
        {OUTPUT_VALUE: cfn_template.CfnTemplate.OUTPUT_VALUE})

    functions = {
        'Fn::GetAZs': cfn_funcs.GetAZs,
        'get_param': hot_funcs.GetParam,
        'get_resource': hot_funcs.GetResource,
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

    deletion_policies = {
        'Delete': rsrc_defn.ResourceDefinition.DELETE,
        'Retain': rsrc_defn.ResourceDefinition.RETAIN,
        'Snapshot': rsrc_defn.ResourceDefinition.SNAPSHOT
    }

    param_schema_class = parameters.HOTParamSchema

    def __getitem__(self, section):
        """"Get the relevant section in the template."""
        # first translate from CFN into HOT terminology if necessary
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
            self.validate_section(self.OUTPUTS, self.OUTPUT_VALUE,
                                  the_section, self.OUTPUT_KEYS)

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

    def validate_section(self, section, sub_section, data, allowed_keys):
        obj_name = section[:-1]
        err_msg = _('"%%s" is not a valid keyword inside a %s '
                    'definition') % obj_name
        args = {'object_name': obj_name, 'sub_section': sub_section}
        message = _('Each %(object_name)s must contain a '
                    '%(sub_section)s key.') % args
        for name, attrs in sorted(data.items()):
            if not attrs:
                raise exception.StackValidationFailed(message=message)
            try:
                for attr, attr_value in six.iteritems(attrs):
                    if attr not in allowed_keys:
                        raise KeyError(err_msg % attr)
                if sub_section not in attrs:
                    raise exception.StackValidationFailed(message=message)
            except AttributeError:
                message = _('"%(section)s" must contain a map of '
                            '%(obj_name)s maps. Found a [%(_type)s] '
                            'instead') % {'section': section,
                                          '_type': type(attrs),
                                          'obj_name': obj_name}
                raise exception.StackValidationFailed(message=message)
            except KeyError as e:
                # an invalid keyword was found
                raise exception.StackValidationFailed(message=e.args[0])

    def _translate_section(self, section, sub_section, data, mapping):

        self.validate_section(section, sub_section, data, mapping)

        cfn_objects = {}
        for name, attrs in sorted(data.items()):
            cfn_object = {}

            for attr, attr_value in six.iteritems(attrs):
                cfn_attr = mapping[attr]
                if cfn_attr is not None:
                    cfn_object[cfn_attr] = attr_value

            cfn_objects[name] = cfn_object

        return cfn_objects

    def _translate_resources(self, resources):
        """Get the resources of the template translated into CFN format."""

        return self._translate_section(self.RESOURCES, self.RES_TYPE,
                                       resources,
                                       self._RESOURCE_HOT_TO_CFN_ATTRS)

    def get_section_name(self, section):
        cfn_to_hot_attrs = dict(
            zip(six.itervalues(self._HOT_TO_CFN_ATTRS),
                six.iterkeys(self._HOT_TO_CFN_ATTRS)))
        return cfn_to_hot_attrs.get(section, section)

    def param_schemata(self, param_defaults=None):
        parameter_section = self.t.get(self.PARAMETERS) or {}
        pdefaults = param_defaults or {}
        for name, schema in six.iteritems(parameter_section):
            if name in pdefaults:
                parameter_section[name]['default'] = pdefaults[name]

        params = six.iteritems(parameter_section)
        return dict((name, self.param_schema_class.from_dict(name, schema))
                    for name, schema in params)

    def parameters(self, stack_identifier, user_params, param_defaults=None):
        return parameters.HOTParameters(stack_identifier, self,
                                        user_params=user_params,
                                        param_defaults=param_defaults)

    def resource_definitions(self, stack):
        resources = self.t.get(self.RESOURCES) or {}
        conditions = self.conditions(stack)

        valid_keys = frozenset(self._RESOURCE_KEYS)

        def defns():
            for name, snippet in six.iteritems(resources):
                try:
                    invalid_keys = set(snippet) - valid_keys
                    if invalid_keys:
                        raise ValueError(_('Invalid keyword(s) inside a '
                                           'resource definition: '
                                           '%s') % ', '.join(invalid_keys))

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

        if self.t.get(self.RESOURCES) is None:
            self.t[self.RESOURCES] = {}
        rendered = definition.render_hot()

        dep_list = rendered.get(self.RES_DEPENDS_ON)
        if dep_list:
            rendered[self.RES_DEPENDS_ON] = [d for d in dep_list
                                             if d in self.t[self.RESOURCES]]

        self.t[self.RESOURCES][name] = rendered

    def add_output(self, definition):
        if self.t.get(self.OUTPUTS) is None:
            self.t[self.OUTPUTS] = {}
        self.t[self.OUTPUTS][definition.name] = definition.render_hot()


class HOTemplate20141016(HOTemplate20130523):
    functions = {
        'get_attr': hot_funcs.GetAtt,
        'get_file': hot_funcs.GetFile,
        'get_param': hot_funcs.GetParam,
        'get_resource': hot_funcs.GetResource,
        'list_join': hot_funcs.Join,
        'resource_facade': hot_funcs.ResourceFacade,
        'str_replace': hot_funcs.Replace,

        'Fn::Select': cfn_funcs.Select,

        # functions removed from 2014-10-16
        'Fn::GetAZs': hot_funcs.Removed,
        'Fn::Join': hot_funcs.Removed,
        'Fn::Split': hot_funcs.Removed,
        'Fn::Replace': hot_funcs.Removed,
        'Fn::Base64': hot_funcs.Removed,
        'Fn::MemberListToMap': hot_funcs.Removed,
        'Fn::ResourceFacade': hot_funcs.Removed,
        'Ref': hot_funcs.Removed,
    }


class HOTemplate20150430(HOTemplate20141016):
    functions = {
        'get_attr': hot_funcs.GetAtt,
        'get_file': hot_funcs.GetFile,
        'get_param': hot_funcs.GetParam,
        'get_resource': hot_funcs.GetResource,
        'list_join': hot_funcs.Join,
        'repeat': hot_funcs.Repeat,
        'resource_facade': hot_funcs.ResourceFacade,
        'str_replace': hot_funcs.Replace,

        'Fn::Select': cfn_funcs.Select,

        # functions added in 2015-04-30
        'digest': hot_funcs.Digest,

        # functions removed from 2014-10-16
        'Fn::GetAZs': hot_funcs.Removed,
        'Fn::Join': hot_funcs.Removed,
        'Fn::Split': hot_funcs.Removed,
        'Fn::Replace': hot_funcs.Removed,
        'Fn::Base64': hot_funcs.Removed,
        'Fn::MemberListToMap': hot_funcs.Removed,
        'Fn::ResourceFacade': hot_funcs.Removed,
        'Ref': hot_funcs.Removed,
    }


class HOTemplate20151015(HOTemplate20150430):
    functions = {
        'get_attr': hot_funcs.GetAttAllAttributes,
        'get_file': hot_funcs.GetFile,
        'get_param': hot_funcs.GetParam,
        'get_resource': hot_funcs.GetResource,
        'list_join': hot_funcs.JoinMultiple,
        'repeat': hot_funcs.Repeat,
        'resource_facade': hot_funcs.ResourceFacade,
        'str_replace': hot_funcs.ReplaceJson,

        # functions added in 2015-04-30
        'digest': hot_funcs.Digest,

        # functions added in 2015-10-15
        'str_split': hot_funcs.StrSplit,

        # functions removed from 2015-10-15
        'Fn::Select': hot_funcs.Removed,

        # functions removed from 2014-10-16
        'Fn::GetAZs': hot_funcs.Removed,
        'Fn::Join': hot_funcs.Removed,
        'Fn::Split': hot_funcs.Removed,
        'Fn::Replace': hot_funcs.Removed,
        'Fn::Base64': hot_funcs.Removed,
        'Fn::MemberListToMap': hot_funcs.Removed,
        'Fn::ResourceFacade': hot_funcs.Removed,
        'Ref': hot_funcs.Removed,
    }


class HOTemplate20160408(HOTemplate20151015):
    functions = {
        'get_attr': hot_funcs.GetAttAllAttributes,
        'get_file': hot_funcs.GetFile,
        'get_param': hot_funcs.GetParam,
        'get_resource': hot_funcs.GetResource,
        'list_join': hot_funcs.JoinMultiple,
        'repeat': hot_funcs.Repeat,
        'resource_facade': hot_funcs.ResourceFacade,
        'str_replace': hot_funcs.ReplaceJson,

        # functions added in 2015-04-30
        'digest': hot_funcs.Digest,

        # functions added in 2015-10-15
        'str_split': hot_funcs.StrSplit,

        # functions added in 2016-04-08
        'map_merge': hot_funcs.MapMerge,

        # functions removed from 2015-10-15
        'Fn::Select': hot_funcs.Removed,

        # functions removed from 2014-10-16
        'Fn::GetAZs': hot_funcs.Removed,
        'Fn::Join': hot_funcs.Removed,
        'Fn::Split': hot_funcs.Removed,
        'Fn::Replace': hot_funcs.Removed,
        'Fn::Base64': hot_funcs.Removed,
        'Fn::MemberListToMap': hot_funcs.Removed,
        'Fn::ResourceFacade': hot_funcs.Removed,
        'Ref': hot_funcs.Removed,
    }


class HOTemplate20161014(HOTemplate20160408):

    CONDITIONS = 'conditions'
    SECTIONS = HOTemplate20160408.SECTIONS + (CONDITIONS,)

    SECTIONS_NO_DIRECT_ACCESS = (HOTemplate20160408.SECTIONS_NO_DIRECT_ACCESS |
                                 set([CONDITIONS]))

    _CFN_TO_HOT_SECTIONS = HOTemplate20160408._CFN_TO_HOT_SECTIONS
    _CFN_TO_HOT_SECTIONS.update({
        cfn_template.CfnTemplate.CONDITIONS: CONDITIONS})

    _EXTRA_RES_KEYS = (
        RES_EXTERNAL_ID, RES_CONDITION
    ) = (
        'external_id', 'condition'
    )
    _RESOURCE_KEYS = HOTemplate20160408._RESOURCE_KEYS + _EXTRA_RES_KEYS

    _RESOURCE_HOT_TO_CFN_ATTRS = HOTemplate20160408._RESOURCE_HOT_TO_CFN_ATTRS
    _RESOURCE_HOT_TO_CFN_ATTRS.update({
        RES_EXTERNAL_ID: None,
        RES_CONDITION: cfn_template.CfnTemplate.RES_CONDITION,
    })

    OUTPUT_CONDITION = 'condition'
    OUTPUT_KEYS = HOTemplate20160408.OUTPUT_KEYS + (OUTPUT_CONDITION,)

    deletion_policies = {
        'Delete': rsrc_defn.ResourceDefinition.DELETE,
        'Retain': rsrc_defn.ResourceDefinition.RETAIN,
        'Snapshot': rsrc_defn.ResourceDefinition.SNAPSHOT,

        # aliases added in 2016-10-14
        'delete': rsrc_defn.ResourceDefinition.DELETE,
        'retain': rsrc_defn.ResourceDefinition.RETAIN,
        'snapshot': rsrc_defn.ResourceDefinition.SNAPSHOT,
    }

    functions = {
        'get_attr': hot_funcs.GetAttAllAttributes,
        'get_file': hot_funcs.GetFile,
        'get_param': hot_funcs.GetParam,
        'get_resource': hot_funcs.GetResource,
        'list_join': hot_funcs.JoinMultiple,
        'repeat': hot_funcs.RepeatWithMap,
        'resource_facade': hot_funcs.ResourceFacade,
        'str_replace': hot_funcs.ReplaceJson,

        # functions added in 2015-04-30
        'digest': hot_funcs.Digest,

        # functions added in 2015-10-15
        'str_split': hot_funcs.StrSplit,

        # functions added in 2016-04-08
        'map_merge': hot_funcs.MapMerge,

        # functions added in 2016-10-14
        'yaql': hot_funcs.Yaql,
        'map_replace': hot_funcs.MapReplace,
        'if': hot_funcs.If,

        # functions removed from 2015-10-15
        'Fn::Select': hot_funcs.Removed,

        # functions removed from 2014-10-16
        'Fn::GetAZs': hot_funcs.Removed,
        'Fn::Join': hot_funcs.Removed,
        'Fn::Split': hot_funcs.Removed,
        'Fn::Replace': hot_funcs.Removed,
        'Fn::Base64': hot_funcs.Removed,
        'Fn::MemberListToMap': hot_funcs.Removed,
        'Fn::ResourceFacade': hot_funcs.Removed,
        'Ref': hot_funcs.Removed,
    }

    condition_functions = {
        'get_param': hot_funcs.GetParam,
        'equals': hot_funcs.Equals,
        'not': hot_funcs.Not,
        'and': hot_funcs.And,
        'or': hot_funcs.Or
    }

    def __init__(self, tmpl, template_id=None, files=None, env=None):
        super(HOTemplate20161014, self).__init__(
            tmpl, template_id, files, env)

        self._parser_condition_functions = {}
        for n, f in six.iteritems(self.functions):
            if not f == hot_funcs.Removed:
                self._parser_condition_functions[n] = function.Invalid
            else:
                self._parser_condition_functions[n] = f
        self._parser_condition_functions.update(self.condition_functions)
        self.merge_sections = [self.PARAMETERS, self.CONDITIONS]

    def _get_condition_definitions(self):
        return self.t.get(self.CONDITIONS, {})

    def _rsrc_defn_args(self, stack, name, data):
        for arg in super(HOTemplate20161014, self)._rsrc_defn_args(stack,
                                                                   name,
                                                                   data):
            yield arg

        parse = functools.partial(self.parse, stack)
        parse_cond = functools.partial(self.parse_condition, stack)

        yield ('external_id',
               self._parse_resource_field(self.RES_EXTERNAL_ID,
                                          (six.string_types,
                                           function.Function),
                                          'string',
                                          name, data, parse))

        yield ('condition',
               self._parse_resource_field(self.RES_CONDITION,
                                          (six.string_types, bool,
                                           function.Function),
                                          'string_or_boolean',
                                          name, data, parse_cond))


class HOTemplate20170224(HOTemplate20161014):
    functions = {
        'get_attr': hot_funcs.GetAttAllAttributes,
        'get_file': hot_funcs.GetFile,
        'get_param': hot_funcs.GetParam,
        'get_resource': hot_funcs.GetResource,
        'list_join': hot_funcs.JoinMultiple,
        'repeat': hot_funcs.RepeatWithMap,
        'resource_facade': hot_funcs.ResourceFacade,
        'str_replace': hot_funcs.ReplaceJson,

        # functions added in 2015-04-30
        'digest': hot_funcs.Digest,

        # functions added in 2015-10-15
        'str_split': hot_funcs.StrSplit,

        # functions added in 2016-04-08
        'map_merge': hot_funcs.MapMerge,

        # functions added in 2016-10-14
        'yaql': hot_funcs.Yaql,
        'map_replace': hot_funcs.MapReplace,
        'if': hot_funcs.If,

        # functions added in 2017-02-24
        'filter': hot_funcs.Filter,
        'str_replace_strict': hot_funcs.ReplaceJsonStrict,

        # functions removed from 2015-10-15
        'Fn::Select': hot_funcs.Removed,

        # functions removed from 2014-10-16
        'Fn::GetAZs': hot_funcs.Removed,
        'Fn::Join': hot_funcs.Removed,
        'Fn::Split': hot_funcs.Removed,
        'Fn::Replace': hot_funcs.Removed,
        'Fn::Base64': hot_funcs.Removed,
        'Fn::MemberListToMap': hot_funcs.Removed,
        'Fn::ResourceFacade': hot_funcs.Removed,
        'Ref': hot_funcs.Removed,
    }

    param_schema_class = parameters.HOTParamSchema20170224


class HOTemplate20170901(HOTemplate20170224):
    functions = {
        'get_attr': hot_funcs.GetAttAllAttributes,
        'get_file': hot_funcs.GetFile,
        'get_param': hot_funcs.GetParam,
        'get_resource': hot_funcs.GetResource,
        'list_join': hot_funcs.JoinMultiple,
        'repeat': hot_funcs.RepeatWithNestedLoop,
        'resource_facade': hot_funcs.ResourceFacade,
        'str_replace': hot_funcs.ReplaceJson,

        # functions added in 2015-04-30
        'digest': hot_funcs.Digest,

        # functions added in 2015-10-15
        'str_split': hot_funcs.StrSplit,

        # functions added in 2016-04-08
        'map_merge': hot_funcs.MapMerge,

        # functions added in 2016-10-14
        'yaql': hot_funcs.Yaql,
        'map_replace': hot_funcs.MapReplace,
        'if': hot_funcs.If,

        # functions added in 2017-02-24
        'filter': hot_funcs.Filter,
        'str_replace_strict': hot_funcs.ReplaceJsonStrict,

        # functions added in 2017-09-01
        'make_url': hot_funcs.MakeURL,
        'list_concat': hot_funcs.ListConcat,
        'str_replace_vstrict': hot_funcs.ReplaceJsonVeryStrict,
        'list_concat_unique': hot_funcs.ListConcatUnique,
        'contains': hot_funcs.Contains,

        # functions removed from 2015-10-15
        'Fn::Select': hot_funcs.Removed,

        # functions removed from 2014-10-16
        'Fn::GetAZs': hot_funcs.Removed,
        'Fn::Join': hot_funcs.Removed,
        'Fn::Split': hot_funcs.Removed,
        'Fn::Replace': hot_funcs.Removed,
        'Fn::Base64': hot_funcs.Removed,
        'Fn::MemberListToMap': hot_funcs.Removed,
        'Fn::ResourceFacade': hot_funcs.Removed,
        'Ref': hot_funcs.Removed,
    }

    condition_functions = {
        'get_param': hot_funcs.GetParam,
        'equals': hot_funcs.Equals,
        'not': hot_funcs.Not,
        'and': hot_funcs.And,
        'or': hot_funcs.Or,

        # functions added in 2017-09-01
        'yaql': hot_funcs.Yaql,
        'contains': hot_funcs.Contains
    }


class HOTemplate20180302(HOTemplate20170901):
    functions = {
        'get_attr': hot_funcs.GetAttAllAttributes,
        'get_file': hot_funcs.GetFile,
        'get_param': hot_funcs.GetParam,
        'get_resource': hot_funcs.GetResource,
        'list_join': hot_funcs.JoinMultiple,
        'repeat': hot_funcs.RepeatWithNestedLoop,
        'resource_facade': hot_funcs.ResourceFacade,
        'str_replace': hot_funcs.ReplaceJson,

        # functions added in 2015-04-30
        'digest': hot_funcs.Digest,

        # functions added in 2015-10-15
        'str_split': hot_funcs.StrSplit,

        # functions added in 2016-04-08
        'map_merge': hot_funcs.MapMerge,

        # functions added in 2016-10-14
        'yaql': hot_funcs.Yaql,
        'map_replace': hot_funcs.MapReplace,
        'if': hot_funcs.If,

        # functions added in 2017-02-24
        'filter': hot_funcs.Filter,
        'str_replace_strict': hot_funcs.ReplaceJsonStrict,

        # functions added in 2017-09-01
        'make_url': hot_funcs.MakeURL,
        'list_concat': hot_funcs.ListConcat,
        'str_replace_vstrict': hot_funcs.ReplaceJsonVeryStrict,
        'list_concat_unique': hot_funcs.ListConcatUnique,
        'contains': hot_funcs.Contains,

        # functions removed from 2015-10-15
        'Fn::Select': hot_funcs.Removed,

        # functions removed from 2014-10-16
        'Fn::GetAZs': hot_funcs.Removed,
        'Fn::Join': hot_funcs.Removed,
        'Fn::Split': hot_funcs.Removed,
        'Fn::Replace': hot_funcs.Removed,
        'Fn::Base64': hot_funcs.Removed,
        'Fn::MemberListToMap': hot_funcs.Removed,
        'Fn::ResourceFacade': hot_funcs.Removed,
        'Ref': hot_funcs.Removed,
    }

    condition_functions = {
        'get_param': hot_funcs.GetParam,
        'equals': hot_funcs.Equals,
        'not': hot_funcs.Not,
        'and': hot_funcs.And,
        'or': hot_funcs.Or,

        # functions added in 2017-09-01
        'yaql': hot_funcs.Yaql,
        'contains': hot_funcs.Contains
    }

    param_schema_class = parameters.HOTParamSchema20180302


class HOTemplate20180831(HOTemplate20180302):
    functions = {
        'get_attr': hot_funcs.GetAttAllAttributes,
        'get_file': hot_funcs.GetFile,
        'get_param': hot_funcs.GetParam,
        'get_resource': hot_funcs.GetResource,
        'list_join': hot_funcs.JoinMultiple,
        'repeat': hot_funcs.RepeatWithNestedLoop,
        'resource_facade': hot_funcs.ResourceFacade,
        'str_replace': hot_funcs.ReplaceJson,

        # functions added in 2015-04-30
        'digest': hot_funcs.Digest,

        # functions added in 2015-10-15
        'str_split': hot_funcs.StrSplit,

        # functions added in 2016-04-08
        'map_merge': hot_funcs.MapMerge,

        # functions added in 2016-10-14
        'yaql': hot_funcs.Yaql,
        'map_replace': hot_funcs.MapReplace,
        'if': hot_funcs.If,

        # functions added in 2017-02-24
        'filter': hot_funcs.Filter,
        'str_replace_strict': hot_funcs.ReplaceJsonStrict,

        # functions added in 2017-09-01
        'make_url': hot_funcs.MakeURL,
        'list_concat': hot_funcs.ListConcat,
        'str_replace_vstrict': hot_funcs.ReplaceJsonVeryStrict,
        'list_concat_unique': hot_funcs.ListConcatUnique,
        'contains': hot_funcs.Contains,

        # functions removed from 2015-10-15
        'Fn::Select': hot_funcs.Removed,

        # functions removed from 2014-10-16
        'Fn::GetAZs': hot_funcs.Removed,
        'Fn::Join': hot_funcs.Removed,
        'Fn::Split': hot_funcs.Removed,
        'Fn::Replace': hot_funcs.Removed,
        'Fn::Base64': hot_funcs.Removed,
        'Fn::MemberListToMap': hot_funcs.Removed,
        'Fn::ResourceFacade': hot_funcs.Removed,
        'Ref': hot_funcs.Removed,
    }

    condition_functions = {
        'get_param': hot_funcs.GetParam,
        'equals': hot_funcs.Equals,
        'not': hot_funcs.Not,
        'and': hot_funcs.And,
        'or': hot_funcs.Or,

        # functions added in 2017-09-01
        'yaql': hot_funcs.Yaql,
        'contains': hot_funcs.Contains
    }
