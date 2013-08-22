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
# -*- coding: utf-8 -*-

from heat.engine import resources
from heat.openstack.common.gettextutils import _

from docutils import nodes
from sphinx.util.compat import Directive


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

            cls_doc = resource_class.__doc__
            if cls_doc:
                para = nodes.paragraph('', cls_doc)
                section.append(para)

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
        if not prop or not prop.get('Type'):
            return 'Value'
        prop_type = prop.get('Type')
        if prop_type == 'List':
            sub_prop = prop.get('Schema')
            sub_type = self._prop_syntax_example(sub_prop)
            return '[%s, %s, ...]' % (sub_type, sub_type)
        elif prop_type == 'Map':
            sub_prop = prop.get('Schema', {})
            sub_props = []
            for sub_key, sub_value in sub_prop.items():
                if sub_value.get('Implemented', True):
                    sub_props.append('"%s": %s' % (
                        sub_key, self._prop_syntax_example(sub_value)))
            return '{%s}' % ', '.join(sub_props or ['...'])
        else:
            return prop_type

    def contribute_hot_syntax(self, parent):
        section = self._section(parent, _('HOT Syntax'), '%s-hot')
        schema = self.resource_class.properties_schema
        props = []
        for prop_key in sorted(schema.keys()):
            prop = schema[prop_key]
            if prop.get('Implemented', True):
                props.append('%s: %s' % (prop_key,
                                         self._prop_syntax_example(prop)))

        template = '''heat_template_version: 2013-05-23
...
resources:
  ...
  the_resource:
    type: %s
    properties:
      %s''' % (self.resource_type, '\n      '.join(props))

        block = nodes.literal_block('', template)
        section.append(block)

    def contribute_yaml_syntax(self, parent):
        section = self._section(parent, _('YAML Syntax'), '%s-yaml')
        schema = self.resource_class.properties_schema
        props = []
        for prop_key in sorted(schema.keys()):
            prop = schema[prop_key]
            if prop.get('Implemented', True):
                props.append('%s: %s' % (prop_key,
                                         self._prop_syntax_example(prop)))

        template = '''HeatTemplateFormatVersion: '2012-12-12'
...
Resources:
  ...
  TheResource:
    Type: %s
    Properties:
      %s''' % (self.resource_type, '\n      '.join(props))

        block = nodes.literal_block('', template)
        section.append(block)

    def contribute_json_syntax(self, parent):
        section = self._section(parent, _('JSON Syntax'), '%s-json')
        schema = self.resource_class.properties_schema

        props = []
        for prop_key in sorted(schema.keys()):
            prop = schema[prop_key]
            if prop.get('Implemented', True):
                props.append('"%s": %s' % (prop_key,
                                           self._prop_syntax_example(prop)))
        template = '''{
  "AWSTemplateFormatVersion" : "2010-09-09",
  ...
  "Resources" : {
    "TheResource": {
      "Type": "%s",
      "Properties": {
        %s
      }
    }
  }
}''' % (self.resource_type, ',\n        '.join(props))
        block = nodes.literal_block('', template)
        section.append(block)

    def contribute_property(self, prop_list, prop_key, prop):
        prop_item = nodes.definition_list_item(
            '', nodes.term('', prop_key))
        prop_list.append(prop_item)

        prop_type = prop.get('Type')
        classifier = prop_type
        if prop.get('MinValue'):
            classifier += _(' from %s') % prop.get('MinValue')
        if prop.get('MaxValue'):
            classifier += _(' up to %s') % prop.get('MaxValue')
        if prop.get('MinLength'):
            classifier += _(' from length %s') % prop.get('MinLength')
        if prop.get('MaxLength'):
            classifier += _(' up to length %s') % prop.get('MaxLength')
        prop_item.append(nodes.classifier('', classifier))

        definition = nodes.definition()
        prop_item.append(definition)

        if not prop.get('Implemented', True):
            para = nodes.inline('', _('Not implemented.'))
            warning = nodes.note('', para)
            definition.append(warning)
            return

        description = prop.get('Description')
        if description:
            para = nodes.paragraph('', description)
            definition.append(para)

        if prop.get('Required'):
            para = nodes.paragraph('', _('Required property.'))
        elif prop.get('Default'):
            para = nodes.paragraph(
                '',
                _('Optional property, defaults to "%s".') %
                prop.get('Default'))
        else:
            para = nodes.paragraph('', _('Optional property.'))
        definition.append(para)

        if prop.get('AllowedPattern'):
            para = nodes.paragraph('', _(
                'Value must match pattern: %s') % prop.get('AllowedPattern'))
            definition.append(para)

        if prop.get('AllowedValues'):
            allowed = [str(a) for a in prop.get('AllowedValues')
                       if a is not None]
            para = nodes.paragraph('', _(
                'Allowed values: %s') % ', '.join(allowed))
            definition.append(para)

        sub_schema = None
        if prop.get('Schema') and prop_type == 'Map':
            para = nodes.emphasis('', _('Map properties:'))
            definition.append(para)
            sub_schema = prop.get('Schema')

        elif prop_type == 'List' and prop.get('Schema', {}).get('Schema'):
            para = nodes.emphasis(
                '', _('List contains maps with the properties:'))
            definition.append(para)
            sub_schema = prop.get('Schema').get('Schema')

        if sub_schema:
            sub_prop_list = nodes.definition_list()
            definition.append(sub_prop_list)
            for sub_prop_key in sorted(sub_schema.keys()):
                sub_prop = sub_schema[sub_prop_key]
                self.contribute_property(sub_prop_list, sub_prop_key, sub_prop)

    def contribute_properties(self, parent):
        schema = self.resource_class.properties_schema
        if not schema:
            return
        section = self._section(parent, _('Properties'), '%s-props')
        prop_list = nodes.definition_list()
        section.append(prop_list)
        for prop_key in sorted(schema.keys()):
            prop = schema[prop_key]
            self.contribute_property(prop_list, prop_key, prop)

    def contribute_attributes(self, parent):
        schema = self.resource_class.attributes_schema
        if not schema:
            return
        section = self._section(parent, _('Attributes'), '%s-attrs')
        prop_list = nodes.definition_list()
        section.append(prop_list)
        for prop_key in sorted(schema.keys()):
            description = schema[prop_key]
            prop_item = nodes.definition_list_item(
                '', nodes.term('', prop_key))
            prop_list.append(prop_item)

            definition = nodes.definition()
            prop_item.append(definition)

            if description:
                def_para = nodes.paragraph('', description)
                definition.append(def_para)


def _all_resources(prefix=None):
    g_env = resources.global_env()
    all_resources = g_env.get_types()
    for resource_type in sorted(all_resources):
        resource_class = g_env.get_class(resource_type)
        if not prefix or resource_type.startswith(prefix):
            yield resource_type, resource_class


def setup(app):

    resources.initialise()
    app.add_node(resourcepages)

    app.add_directive('resourcepages', ResourcePages)
