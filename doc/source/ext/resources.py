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
# -*- coding: utf-8 -*-

import itertools

from docutils import core
from docutils import nodes
import pydoc
from sphinx.util.compat import Directive

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import environment
from heat.engine import plugin_manager
from heat.engine import properties
from heat.engine import resources
from heat.engine import support


global_env = environment.Environment({}, user_env=False)


class resourcepages(nodes.General, nodes.Element):
    pass


class ResourcePages(Directive):
    has_content = False
    required_arguments = 0
    optional_arguments = 1
    final_argument_whitespace = False
    option_spec = {}

    def run(self):
        prefix = self.arguments and self.arguments.pop() or None
        content = []
        for resource_type, resource_class in _all_resources(prefix):
            self.resource_type = resource_type
            self.resource_class = resource_class
            section = self._section(content, resource_type, '%s')

            self.props_schemata = properties.schemata(
                self.resource_class.properties_schema)
            self.attrs_schemata = attributes.schemata(
                self.resource_class.attributes_schema)

            if resource_class.support_status.status == support.DEPRECATED:
                sstatus = resource_class.support_status.to_dict()
                msg = _('%(status)s')
                if sstatus['message'] is not None:
                    msg = _('%(status)s - %(message)s')
                para = nodes.inline('', msg % sstatus)
                warning = nodes.note('', para)
                section.append(warning)

            cls_doc = pydoc.getdoc(resource_class)
            if cls_doc:
                # allow for rst in the class comments
                cls_nodes = core.publish_doctree(cls_doc).children
                section.extend(cls_nodes)

            self.contribute_properties(section)
            self.contribute_attributes(section)

            self.contribute_hot_syntax(section)
            self.contribute_yaml_syntax(section)
            self.contribute_json_syntax(section)

        return content

    def _section(self, parent, title, id_pattern):
        id = id_pattern % self.resource_type
        section = nodes.section(ids=[id])
        parent.append(section)
        title = nodes.title('', title)
        section.append(title)
        return section

    def _prop_syntax_example(self, prop):
        if not prop:
            return 'Value'
        if prop.type == properties.Schema.LIST:
            schema = lambda i: prop.schema[i] if prop.schema else None
            sub_type = [self._prop_syntax_example(schema(i))
                        for i in range(2)]
            return '[%s, %s, ...]' % tuple(sub_type)
        elif prop.type == properties.Schema.MAP:
            def sub_props():
                for sub_key, sub_value in prop.schema.items():
                    if sub_value.implemented:
                        yield '"%s": %s' % (
                            sub_key, self._prop_syntax_example(sub_value))
            return '{%s}' % (', '.join(sub_props()) if prop.schema else '...')
        else:
            return prop.type

    def contribute_hot_syntax(self, parent):
        section = self._section(parent, _('HOT Syntax'), '%s-hot')
        props = []
        for prop_key in sorted(self.props_schemata.keys()):
            prop = self.props_schemata[prop_key]
            if (prop.implemented
                    and prop.support_status.status == support.SUPPORTED):
                props.append('%s: %s' % (prop_key,
                                         self._prop_syntax_example(prop)))

        props_str = ''
        if props:
            props_str = '''\n    properties:
      %s''' % ('\n      '.join(props))

        template = '''heat_template_version: 2013-05-23
...
resources:
  ...
  the_resource:
    type: %s%s''' % (self.resource_type, props_str)

        block = nodes.literal_block('', template, language="hot")
        section.append(block)

    def contribute_yaml_syntax(self, parent):
        section = self._section(parent, _('YAML Syntax'), '%s-yaml')
        props = []
        for prop_key in sorted(self.props_schemata.keys()):
            prop = self.props_schemata[prop_key]
            if (prop.implemented
                    and prop.support_status.status == support.SUPPORTED):
                props.append('%s: %s' % (prop_key,
                                         self._prop_syntax_example(prop)))

        props_str = ''
        if props:
            props_str = '''\n    Properties:
      %s''' % ('\n      '.join(props))

        template = '''HeatTemplateFormatVersion: '2012-12-12'
...
Resources:
  ...
  TheResource:
    Type: %s%s''' % (self.resource_type, props_str)

        block = nodes.literal_block('', template, language='yaml')
        section.append(block)

    def contribute_json_syntax(self, parent):
        section = self._section(parent, _('JSON Syntax'), '%s-json')

        props = []
        for prop_key in sorted(self.props_schemata.keys()):
            prop = self.props_schemata[prop_key]
            if (prop.implemented
                    and prop.support_status.status == support.SUPPORTED):
                props.append('"%s": %s' % (prop_key,
                                           self._prop_syntax_example(prop)))

        props_str = ''
        if props:
            props_str = ''',\n      "Properties": {
        %s
      }''' % (',\n        '.join(props))

        template = '''{
  "AWSTemplateFormatVersion" : "2010-09-09",
  ...
  "Resources" : {
    "TheResource": {
      "Type": "%s"%s
    }
  }
}''' % (self.resource_type, props_str)

        block = nodes.literal_block('', template, language="json")
        section.append(block)

    @staticmethod
    def cmp_prop(x, y):
        x_key, x_prop = x
        y_key, y_prop = y
        if x_prop.support_status.status == y_prop.support_status.status:
            return cmp(x_key, y_key)
        if x_prop.support_status.status == support.SUPPORTED:
            return -1
        if x_prop.support_status.status == support.DEPRECATED:
            return 1
        return cmp(x_prop.support_status.status,
                   y_prop.support_status.status)

    def contribute_property(self, prop_list, prop_key, prop):
        prop_item = nodes.definition_list_item(
            '', nodes.term('', prop_key))
        prop_list.append(prop_item)

        prop_item.append(nodes.classifier('', prop.type))

        definition = nodes.definition()
        prop_item.append(definition)

        if prop.support_status.status != support.SUPPORTED:
            sstatus = prop.support_status.to_dict()
            msg = _('%(status)s')
            if sstatus['message'] is not None:
                msg = _('%(status)s - %(message)s')
            para = nodes.inline('', msg % sstatus)
            warning = nodes.note('', para)
            definition.append(warning)

        if not prop.implemented:
            para = nodes.inline('', _('Not implemented.'))
            warning = nodes.note('', para)
            definition.append(warning)
            return

        if prop.description:
            para = nodes.paragraph('', prop.description)
            definition.append(para)

        if prop.update_allowed:
            para = nodes.paragraph('',
                                   _('Can be updated without replacement.'))
            definition.append(para)
        elif prop.immutable:
            para = nodes.paragraph('', _('Updates are not supported. '
                                         'Resource update will fail on any '
                                         'attempt to update this property.'))
            definition.append(para)
        else:
            para = nodes.paragraph('', _('Updates cause replacement.'))
            definition.append(para)

        if prop.required:
            para = nodes.paragraph('', _('Required property.'))
        elif prop.default is not None:
            para = nodes.paragraph(
                '',
                _('Optional property, defaults to "%s".') % prop.default)
        else:
            para = nodes.paragraph('', _('Optional property.'))
        definition.append(para)

        for constraint in prop.constraints:
            para = nodes.paragraph('', str(constraint))
            definition.append(para)

        sub_schema = None
        if prop.schema and prop.type == properties.Schema.MAP:
            para = nodes.paragraph()
            emph = nodes.emphasis('', _('Map properties:'))
            para.append(emph)
            definition.append(para)
            sub_schema = prop.schema

        elif prop.schema and prop.type == properties.Schema.LIST:
            para = nodes.paragraph()
            emph = nodes.emphasis('', _('List contents:'))
            para.append(emph)
            definition.append(para)
            sub_schema = prop.schema

        if sub_schema:
            sub_prop_list = nodes.definition_list()
            definition.append(sub_prop_list)
            for sub_prop_key, sub_prop in sorted(sub_schema.items(),
                                                 self.cmp_prop):
                self.contribute_property(
                    sub_prop_list, sub_prop_key, sub_prop)

    def contribute_properties(self, parent):
        if not self.props_schemata:
            return
        section = self._section(parent, _('Properties'), '%s-props')
        prop_list = nodes.definition_list()
        section.append(prop_list)

        for prop_key, prop in sorted(self.props_schemata.items(),
                                     self.cmp_prop):
            self.contribute_property(prop_list, prop_key, prop)

    def contribute_attributes(self, parent):
        if not self.attrs_schemata:
            return
        section = self._section(parent, _('Attributes'), '%s-attrs')
        prop_list = nodes.definition_list()
        section.append(prop_list)
        for prop_key, prop in sorted(self.attrs_schemata.items()):
            description = prop.description
            prop_item = nodes.definition_list_item(
                '', nodes.term('', prop_key))
            prop_list.append(prop_item)

            definition = nodes.definition()
            prop_item.append(definition)

            if prop.support_status.status != support.SUPPORTED:
                sstatus = prop.support_status.to_dict()
                msg = _('%(status)s')
                if sstatus['message'] is not None:
                    msg = _('%(status)s - %(message)s')
                para = nodes.inline('', msg % sstatus)
                warning = nodes.note('', para)
                definition.append(warning)

            if description:
                def_para = nodes.paragraph('', description)
                definition.append(def_para)


def _all_resources(prefix=None):
    type_names = sorted(global_env.get_types())
    if prefix is not None:
        def prefix_match(name):
            return name.startswith(prefix)

        type_names = itertools.ifilter(prefix_match, type_names)

    def resource_type(name):
        return name, global_env.get_class(name)

    return itertools.imap(resource_type, type_names)


def _load_all_resources():
    manager = plugin_manager.PluginManager('heat.engine.resources')
    resource_mapping = plugin_manager.PluginMapping('resource')
    res_plugin_mappings = resource_mapping.load_all(manager)

    resources._register_resources(global_env, res_plugin_mappings)
    environment.read_global_environment(global_env)


def setup(app):
    _load_all_resources()
    app.add_node(resourcepages)

    app.add_directive('resourcepages', ResourcePages)
