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

from functools import cmp_to_key
import json
import pydoc

from docutils import core
from docutils import nodes
from docutils.parsers import rst
import six

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import plugin_manager
from heat.engine import properties
from heat.engine import support

_CODE_NAMES = {'2013.1': 'Grizzly',
               '2013.2': 'Havana',
               '2014.1': 'Icehouse',
               '2014.2': 'Juno',
               '2015.1': 'Kilo',
               '5.0.0': 'Liberty',
               '6.0.0': 'Mitaka',
               '7.0.0': 'Newton',
               '8.0.0': 'Ocata',
               '9.0.0': 'Pike',
               '10.0.0': 'Queens',
               '11.0.0': 'Rocky',
               '12.0.0': 'Stein'}

all_resources = {}


class integratedrespages(nodes.General, nodes.Element):
    pass


class unsupportedrespages(nodes.General, nodes.Element):
    pass


class contribresourcepages(nodes.General, nodes.Element):
    pass


class ResourcePages(rst.Directive):
    has_content = False
    required_arguments = 0
    optional_arguments = 1
    final_argument_whitespace = False
    option_spec = {}

    def path(self):
        return None

    def statuses(self):
        return support.SUPPORT_STATUSES

    def run(self):
        prefix = self.arguments and self.arguments.pop() or None
        content = []
        for resource_type, resource_classes in _filter_resources(
                prefix, self.path(), self.statuses()):
            for resource_class in resource_classes:
                self.resource_type = resource_type
                self.resource_class = resource_class
                section = self._section(content, resource_type, '%s')

                self.props_schemata = properties.schemata(
                    self.resource_class.properties_schema)
                self.attrs_schemata = attributes.schemata(
                    self.resource_class.attributes_schema)
                # NOTE(prazumovsky): Adding base_attributes_schema dict to
                # Resource class should means adding new attributes from this
                # dict to documentation of each resource, else there is no
                # chance to learn about base attributes.
                self.attrs_schemata.update(
                    self.resource_class.base_attributes_schema)
                self.update_policy_schemata = properties.schemata(
                    self.resource_class.update_policy_schema)

                self._status_str(resource_class.support_status, section)

                cls_doc = pydoc.getdoc(resource_class)
                if cls_doc:
                    # allow for rst in the class comments
                    cls_nodes = core.publish_doctree(cls_doc).children
                    section.extend(cls_nodes)

                self.contribute_properties(section)
                self.contribute_attributes(section)
                self.contribute_update_policy(section)

                self.contribute_hot_syntax(section)

        return content

    def _version_str(self, version):
        if version in _CODE_NAMES:
            return _("%(version)s (%(code)s)") % {'version': version,
                                                  'code': _CODE_NAMES[version]}
        else:
            return version

    def _status_str(self, support_status, section):
        while support_status is not None:
            sstatus = support_status.to_dict()
            if sstatus['status'] is support.SUPPORTED:
                msg = _('Available')
            else:
                msg = sstatus['status']
            if sstatus['version'] is not None:
                msg = _('%(msg)s since %(version)s') % {
                    'msg': msg,
                    'version': self._version_str(sstatus['version'])}
            if sstatus['message'] is not None:
                msg = _('%(msg)s - %(status_msg)s') % {
                    'msg': msg,
                    'status_msg': sstatus['message']}
            if not (sstatus['status'] == support.SUPPORTED and
                    sstatus['version'] is None):
                para = nodes.inline('', msg)
                para['classes'] = ['versionmodified']
                parent_para = nodes.paragraph()
                parent_para['classes'] = ['versionsupport']
                parent_para.append(para)
                note = nodes.topic()
                if sstatus['status'] == support.SUPPORTED:
                    note['classes'] = ['versionadded']
                else:
                    note['classes'] = ['deprecated']
                note.append(parent_para)
                section.append(note)
            support_status = support_status.previous_status

    def _section(self, parent, title, id_pattern):
        id = id_pattern % self.resource_type
        section = nodes.section(ids=[id])
        parent.append(section)
        title = nodes.title('', title)
        section.append(title)
        return section

    def _prop_section(self, parent, title, id_pattern):
        id = id_pattern % self.resource_type
        section = nodes.section(ids=[id])
        parent.append(section)

        # Ignore title generated for list items
        if title != '*':
            title = nodes.term('', title)
            ref = nodes.reference('', u'\xb6')
            ref['classes'] = ['headerlink']
            ref['refid'] = id
            title.append(ref)
            section.append(title)
        field = nodes.definition()
        section.append(field)
        return field

    def _prop_syntax_example(self, prop):
        if not prop:
            return 'Value'
        if prop.type == properties.Schema.LIST:

            def schema(i):
                return prop.schema[i] if prop.schema else None

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

        template = '''heat_template_version: 2015-04-30
...
resources:
  ...
  the_resource:
    type: %s%s''' % (self.resource_type, props_str)

        block = nodes.literal_block(template, template, language="yaml")
        section.append(block)

    @staticmethod
    def cmp_prop(x, y):
        x_key, x_prop = x
        y_key, y_prop = y
        if x_prop.support_status.status == y_prop.support_status.status:
            return (x_key > y_key) - (x_key < y_key)
        x_status = x_prop.support_status.status
        y_status = y_prop.support_status.status
        if x_status == support.SUPPORTED:
            return -1
        if x_status == support.DEPRECATED:
            return 1
        return (x_status > y_status) - (x_status < y_status)

    def contribute_property(self, parent, prop_key, prop, upd_para=None,
                            id_pattern_prefix=None, sub_prop=False):
        if not id_pattern_prefix:
            id_pattern_prefix = '%s-prop'
        id_pattern = id_pattern_prefix + '-' + prop_key

        definition = self._prop_section(parent, prop_key, id_pattern)

        self._status_str(prop.support_status, definition)

        if not prop.implemented:
            para = nodes.line('', _('Not implemented.'))
            note = nodes.note('', para)
            definition.append(note)
            return

        if sub_prop and prop.type not in (properties.Schema.LIST,
                                          properties.Schema.MAP):
            if prop.required:
                para = nodes.line('', _('Required.'))
                definition.append(para)
            else:
                para = nodes.line('', _('Optional.'))
                definition.append(para)

        if prop.description:
            para = nodes.line('', prop.description)
            definition.append(para)

        type = nodes.line('', _('%s value expected.') % prop.type)
        definition.append(type)

        if upd_para is not None:
            definition.append(upd_para)
        else:
            if prop.update_allowed:
                upd_para = nodes.line(
                    '', _('Can be updated without replacement.'))
                definition.append(upd_para)
            elif prop.immutable:
                upd_para = nodes.line('', _('Updates are not supported. '
                                            'Resource update will fail on '
                                            'any attempt to update this '
                                            'property.'))
                definition.append(upd_para)
            else:
                upd_para = nodes.line('', _('Updates cause replacement.'))
                definition.append(upd_para)

        if prop.default is not None:
            para = nodes.line('', _('Defaults to '))
            default = nodes.literal('', json.dumps(prop.default))
            para.append(default)
            definition.append(para)

        for constraint in prop.constraints:
            para = nodes.line('', str(constraint))
            definition.append(para)

        sub_schema = None
        if prop.schema and prop.type == properties.Schema.MAP:
            para = nodes.line()
            emph = nodes.emphasis('', _('Map properties:'))
            para.append(emph)
            definition.append(para)
            sub_schema = prop.schema

        elif prop.schema and prop.type == properties.Schema.LIST:
            para = nodes.line()
            emph = nodes.emphasis('', _('List contents:'))
            para.append(emph)
            definition.append(para)
            sub_schema = prop.schema

        if sub_schema:
            indent = nodes.definition_list()
            definition.append(indent)
            for _key, _prop in sorted(sub_schema.items(),
                                      key=cmp_to_key(self.cmp_prop)):
                if _prop.support_status.status != support.HIDDEN:
                    self.contribute_property(
                        indent, _key, _prop, upd_para, id_pattern,
                        sub_prop=True)

    def contribute_properties(self, parent):
        if not self.props_schemata:
            return

        props = dict((k, v) for k, v in self.props_schemata.items()
                     if v.support_status.status != support.HIDDEN)

        required_props = dict((k, v) for k, v in props.items()
                              if v.required)
        if required_props:
            section = self._section(
                parent, _('Required Properties'), '%s-props-req')
            definition_list = nodes.definition_list()
            section.append(definition_list)

            for prop_key, prop in sorted(required_props.items(),
                                         key=cmp_to_key(self.cmp_prop)):
                self.contribute_property(definition_list, prop_key, prop)

        optional_props = dict((k, v) for k, v in props.items()
                              if not v.required)
        if optional_props:
            section = self._section(
                parent, _('Optional Properties'), '%s-props-opt')
            definition_list = nodes.definition_list()
            section.append(definition_list)

            for prop_key, prop in sorted(optional_props.items(),
                                         key=cmp_to_key(self.cmp_prop)):
                self.contribute_property(definition_list, prop_key, prop)

    def contribute_attributes(self, parent):
        if not self.attrs_schemata:
            return
        section = self._section(parent, _('Attributes'), '%s-attrs')
        for prop_key, prop in sorted(self.attrs_schemata.items()):
            if prop.support_status.status != support.HIDDEN:
                description = prop.description
                attr_section = self._prop_section(
                    section, prop_key, '%s-attr-' + prop_key)

                self._status_str(prop.support_status, attr_section)

                if description:
                    def_para = nodes.paragraph('', description)
                    attr_section.append(def_para)

    def contribute_update_policy(self, parent):
        if not self.update_policy_schemata:
            return
        section = self._section(parent, _('update_policy'), '%s-updpolicy')
        for _key, _prop in sorted(self.update_policy_schemata.items(),
                                  key=cmp_to_key(self.cmp_prop)):
            self.contribute_property(section, _key, _prop)


class IntegrateResourcePages(ResourcePages):

    def path(self):
        return 'heat.engine.resources'

    def statuses(self):
        return [support.SUPPORTED]


class UnsupportedResourcePages(ResourcePages):

    def path(self):
        return 'heat.engine.resources'

    def statuses(self):
        return [s for s in support.SUPPORT_STATUSES if s != support.SUPPORTED]


class ContribResourcePages(ResourcePages):

    def path(self):
        return 'heat.engine.plugins'


def _filter_resources(prefix=None, path=None, statuses=None):

    def not_hidden_match(cls):
        return cls.support_status.status != support.HIDDEN

    def prefix_match(name):
        return prefix is None or name.startswith(prefix)

    def path_match(cls):
        return path is None or cls.__module__.startswith(path)

    def status_match(cls):
        return cls.support_status.status in statuses

    statuses = statuses or []
    filtered_resources = {}
    for name in sorted(all_resources.keys()):
        if prefix_match(name):
            for cls in all_resources.get(name):
                if (path_match(cls) and status_match(cls) and
                        not_hidden_match(cls)):
                    if filtered_resources.get(name) is not None:
                        filtered_resources[name].append(cls)
                    else:
                        filtered_resources[name] = [cls]

    return sorted(six.iteritems(filtered_resources))


def _load_all_resources():
    from oslo_log import log as logging
    logging.getLogger('heat.engine.environment').logger.setLevel(logging.ERROR)

    manager = plugin_manager.PluginManager('heat.engine.resources')
    resource_mapping = plugin_manager.PluginMapping('resource')
    res_plugin_mappings = resource_mapping.load_all(manager)

    for mapping in res_plugin_mappings:
        name, cls = mapping
        if all_resources.get(name) is not None:
            all_resources[name].append(cls)
        else:
            all_resources[name] = [cls]


def link_resource(app, env, node, contnode):
    reftarget = node.attributes['reftarget']
    for resource_name in all_resources:
        if resource_name.lower() == reftarget.lower():
            refnode = nodes.reference('', '', internal=True)
            refnode['reftitle'] = resource_name
            if resource_name.startswith('AWS'):
                source = 'template_guide/cfn'
            else:
                source = 'template_guide/openstack'
            uri = app.builder.get_relative_uri(
                node.attributes['refdoc'], source)
            refnode['refuri'] = '%s#%s' % (uri, resource_name)
            refnode.append(contnode)
            return refnode


def setup(app):
    _load_all_resources()
    app.add_node(integratedrespages)

    app.add_directive('integratedrespages', IntegrateResourcePages)

    app.add_node(unsupportedrespages)

    app.add_directive('unsupportedrespages', UnsupportedResourcePages)

    app.add_node(contribresourcepages)

    app.add_directive('contribrespages', ContribResourcePages)

    app.connect('missing-reference', link_resource)
