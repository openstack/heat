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

from heat.common import exception
from heat.common.i18n import _
from heat.engine.cfn import functions as cfn_funcs
from heat.engine.cfn import template as cfn_template
from heat.engine import function
from heat.engine.hot import functions as hot_funcs
from heat.engine.hot import parameters
from heat.engine import rsrc_defn
from heat.engine import template


class HOTemplate20130523(template.Template):
    """A Heat Orchestration Template format stack template."""

    SECTIONS = (
        VERSION, DESCRIPTION, PARAMETER_GROUPS,
        PARAMETERS, RESOURCES, OUTPUTS, MAPPINGS
    ) = (
        'heat_template_version', 'description', 'parameter_groups',
        'parameters', 'resources', 'outputs', '__undefined__'
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

    deletion_policies = {
        'Delete': rsrc_defn.ResourceDefinition.DELETE,
        'Retain': rsrc_defn.ResourceDefinition.RETAIN,
        'Snapshot': rsrc_defn.ResourceDefinition.SNAPSHOT
    }

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

    def _translate_section(self, section, sub_section, data, mapping):

        self.validate_section(section, sub_section, data, mapping)

        cfn_objects = {}
        for name, attrs in sorted(data.items()):
            cfn_object = {}

            for attr, attr_value in six.iteritems(attrs):
                cfn_attr = mapping[attr]
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
        return dict((name, parameters.HOTParamSchema.from_dict(name, schema))
                    for name, schema in params)

    def parameters(self, stack_identifier, user_params, param_defaults=None):
        return parameters.HOTParameters(stack_identifier, self,
                                        user_params=user_params,
                                        param_defaults=param_defaults)

    def validate_resource_definitions(self, stack):
        resources = self.t.get(self.RESOURCES) or {}
        allowed_keys = set(self._RESOURCE_KEYS)

        try:
            for name, snippet in resources.items():
                data = self.parse(stack, snippet)

                if not self.validate_resource_key_type(self.RES_TYPE,
                                                       six.string_types,
                                                       'string',
                                                       allowed_keys,
                                                       name, data):
                    args = {'name': name, 'type_key': self.RES_TYPE}
                    msg = _('Resource %(name)s is missing '
                            '"%(type_key)s"') % args
                    raise KeyError(msg)

                self.validate_resource_key_type(
                    self.RES_PROPERTIES,
                    (collections.Mapping, function.Function),
                    'object', allowed_keys, name, data)
                self.validate_resource_key_type(
                    self.RES_METADATA,
                    (collections.Mapping, function.Function),
                    'object', allowed_keys, name, data)
                self.validate_resource_key_type(
                    self.RES_DEPENDS_ON,
                    collections.Sequence,
                    'list or string', allowed_keys, name, data)
                self.validate_resource_key_type(
                    self.RES_DELETION_POLICY,
                    (six.string_types, function.Function),
                    'string', allowed_keys, name, data)
                self.validate_resource_key_type(
                    self.RES_UPDATE_POLICY,
                    (collections.Mapping, function.Function),
                    'object', allowed_keys, name, data)
        except (TypeError, ValueError) as ex:
            raise exception.StackValidationFailed(message=six.text_type(ex))

    def resource_definitions(self, stack):
        resources = self.t.get(self.RESOURCES) or {}
        parsed_resources = self.parse(stack, resources)
        return dict((name, self.rsrc_defn_from_snippet(name, data))
                    for name, data in parsed_resources.items())

    @classmethod
    def rsrc_defn_from_snippet(cls, name, data):
        depends = data.get(cls.RES_DEPENDS_ON)
        if isinstance(depends, six.string_types):
            depends = [depends]

        deletion_policy = function.resolve(
            data.get(cls.RES_DELETION_POLICY))
        if deletion_policy is not None:
            if deletion_policy not in cls.deletion_policies:
                msg = _('Invalid deletion policy "%s"') % deletion_policy
                raise exception.StackValidationFailed(message=msg)
            else:
                deletion_policy = cls.deletion_policies[deletion_policy]
        kwargs = {
            'resource_type': data.get(cls.RES_TYPE),
            'properties': data.get(cls.RES_PROPERTIES),
            'metadata': data.get(cls.RES_METADATA),
            'depends': depends,
            'deletion_policy': deletion_policy,
            'update_policy': data.get(cls.RES_UPDATE_POLICY),
            'description': None
        }

        return rsrc_defn.ResourceDefinition(name, **kwargs)

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
        'get_resource': cfn_funcs.ResourceRef,
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
        'get_resource': cfn_funcs.ResourceRef,
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
        'get_resource': cfn_funcs.ResourceRef,
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
        'get_resource': cfn_funcs.ResourceRef,
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

        # functions added in 2016-10-14
        'yaql': hot_funcs.Yaql,
        'equals': cfn_funcs.Equals,

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
