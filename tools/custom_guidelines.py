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

import argparse
import re
import sys

from oslo_log import log
import six

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import plugin_manager
from heat.engine import support

LOG = log.getLogger(__name__)


class HeatCustomGuidelines(object):

    _RULES = ['resource_descriptions', 'trailing_spaces']

    def __init__(self, exclude):
        self.error_count = 0
        self.resources_classes = []
        all_resources = _load_all_resources()
        for resource_type in all_resources:
            for rsrc_cls in all_resources[resource_type]:
                module = rsrc_cls.__module__
                # Skip hidden resources check guidelines
                if rsrc_cls.support_status.status == support.HIDDEN:
                    continue
                # Skip resources, which defined as template resource in
                # environment or cotrib resource
                if module in ('heat.engine.resources.template_resource',
                              'heat.engine.plugins'):
                    continue
                # Skip manually excluded folders
                path = module.replace('.', '/')
                if any(path.startswith(excl_path) for excl_path in exclude):
                    continue
                self.resources_classes.append(rsrc_cls)

    def run_check(self):
        print(_('Heat custom guidelines check started.'))
        for rule in self._RULES:
            getattr(self, 'check_%s' % rule)()
        if self.error_count > 0:
            print(_('Heat custom guidelines check failed - '
                    'found %s errors.') % self.error_count)
            sys.exit(1)
        else:
            print(_('Heat custom guidelines check succeeded.'))

    def check_resource_descriptions(self):
        for cls in self.resources_classes:
            # check resource's description
            self._check_resource_description(cls)
            # check properties' descriptions
            self._check_resource_schemas(cls, cls.properties_schema,
                                         'property')
            # check attributes' descriptions
            self._check_resource_schemas(cls, cls.attributes_schema,
                                         'attribute')
            # check methods descriptions
            self._check_resource_methods(cls)

    def _check_resource_description(self, resource):
        description = resource.__doc__
        if resource.support_status.status not in (support.SUPPORTED,
                                                  support.UNSUPPORTED):
            return
        kwargs = {'path': resource.__module__, 'details': resource.__name__}
        if not description:
            kwargs.update({'message': _("Resource description missing, "
                                        "should add resource description "
                                        "about resource's purpose")})
            self.print_guideline_error(**kwargs)
            return

        doclines = [key.strip() for key in description.split('\n')]
        if len(doclines) == 1 or (len(doclines) == 2 and doclines[-1] == ''):
            kwargs.update({'message': _("Resource description missing, "
                                        "should add resource description "
                                        "about resource's purpose")})
            self.print_guideline_error(**kwargs)
            return

        self._check_description_summary(doclines[0], kwargs, 'resource')
        self._check_description_details(doclines, kwargs, 'resource')

    def _check_resource_schemas(self, resource, schema, schema_name,
                                error_path=None):
        for key, value in six.iteritems(schema):
            if error_path is None:
                error_path = [resource.__name__, key]
            else:
                error_path.append(key)
            # need to check sub-schema of current schema, if exists
            if (hasattr(value, 'schema') and
                    getattr(value, 'schema') is not None):
                self._check_resource_schemas(resource, value.schema,
                                             schema_name, error_path)
            description = value.description
            kwargs = {'path': resource.__module__, 'details': error_path}
            if description is None:
                if (value.support_status.status == support.SUPPORTED and
                        not isinstance(value.schema,
                                       constraints.AnyIndexDict) and
                        not isinstance(schema, constraints.AnyIndexDict)):
                    kwargs.update({'message': _("%s description "
                                                "missing, need to add "
                                                "description about property's "
                                                "purpose") % schema_name})
                    self.print_guideline_error(**kwargs)
                error_path.pop()
                continue
            self._check_description_summary(description, kwargs, schema_name)
            error_path.pop()

    def _check_resource_methods(self, resource):
        for method in six.itervalues(resource.__dict__):
            # need to skip non-functions attributes
            if not callable(method):
                continue
            description = method.__doc__
            if not description:
                continue
            if method.__name__.startswith('__'):
                continue
            doclines = [key.strip() for key in description.split('\n')]
            kwargs = {'path': resource.__module__,
                      'details': [resource.__name__, method.__name__]}

            self._check_description_summary(doclines[0], kwargs, 'method')

            if len(doclines) == 2:
                kwargs.update({'message': _('Method description summary '
                                            'should be in one line')})
                self.print_guideline_error(**kwargs)
                continue

            if len(doclines) > 1:
                self._check_description_details(doclines, kwargs, 'method')

    def check_trailing_spaces(self):
        for cls in self.resources_classes:
            try:
                cls_file = open(cls.__module__.replace('.', '/') + '.py')
            except IOError as ex:
                LOG.warning('Cannot perform trailing spaces check on '
                            'resource module: %s', six.text_type(ex))
                continue
            lines = [line.strip() for line in cls_file.readlines()]
            idx = 0
            kwargs = {'path': cls.__module__}
            while idx < len(lines):
                if ('properties_schema' in lines[idx] or
                        'attributes_schema' in lines[idx]):
                    level = len(re.findall(r'(\{|\()', lines[idx]))
                    level -= len(re.findall(r'(\}|\))', lines[idx]))
                    idx += 1
                    while level != 0:
                        level += len(re.findall(r'(\{|\()', lines[idx]))
                        level -= len(re.findall(r'(\}|\))', lines[idx]))
                        if re.search("^((\'|\") )", lines[idx]):
                            kwargs.update(
                                {'details': 'line %s' % idx,
                                 'message': _('Trailing whitespace should '
                                              'be on previous line'),
                                 'snippet': lines[idx]})
                            self.print_guideline_error(**kwargs)
                        elif (re.search("(\\S(\'|\"))$", lines[idx - 1]) and
                              re.search("^((\'|\")\\S)", lines[idx])):
                            kwargs.update(
                                {'details': 'line %s' % (idx - 1),
                                 'message': _('Omitted whitespace at the '
                                              'end of the line'),
                                 'snippet': lines[idx - 1]})
                            self.print_guideline_error(**kwargs)
                        idx += 1
                idx += 1

    def _check_description_summary(self, description, error_kwargs,
                                   error_key):
        if re.search("^[a-z]", description):
            error_kwargs.update(
                {'message': _('%s description summary should start '
                              'with uppercase letter') % error_key.title(),
                 'snippet': description})
            self.print_guideline_error(**error_kwargs)
        if not description.endswith('.'):
            error_kwargs.update(
                {'message': _('%s description summary omitted '
                              'terminator at the end') % error_key.title(),
                 'snippet': description})
            self.print_guideline_error(**error_kwargs)
        if re.search(r"\s{2,}", description):
            error_kwargs.update(
                {'message': _('%s description contains double or more '
                              'whitespaces') % error_key.title(),
                 'snippet': description})
            self.print_guideline_error(**error_kwargs)

    def _check_description_details(self, doclines, error_kwargs,
                                   error_key):
        if re.search(r"\S", doclines[1]):
            error_kwargs.update(
                {'message': _('%s description summary and '
                              'main resource description should be '
                              'separated by blank line') % error_key.title(),
                 'snippet': doclines[0]})
            self.print_guideline_error(**error_kwargs)

        if re.search("^[a-z]", doclines[2]):
            error_kwargs.update(
                {'message': _('%s description should start '
                              'with with uppercase '
                              'letter') % error_key.title(),
                 'snippet': doclines[2]})
            self.print_guideline_error(**error_kwargs)

        if doclines[-1] != '':
            error_kwargs.update(
                {'message': _('%s description multistring '
                              'should have singly closing quotes at '
                              'the next line') % error_key.title(),
                 'snippet': doclines[-1]})
            self.print_guideline_error(**error_kwargs)

        params = False
        for line in doclines[1:]:
                if re.search(r"\s{2,}", line):
                    error_kwargs.update(
                        {'message': _('%s description '
                                      'contains double or more '
                                      'whitespaces') % error_key.title(),
                         'snippet': line})
                    self.print_guideline_error(**error_kwargs)
                if re.search("^(:param|:type|:returns|:rtype|:raises)",
                             line):
                    params = True
        if not params and not doclines[-2].endswith('.'):
            error_kwargs.update(
                {'message': _('%s description omitted '
                              'terminator at the end') % error_key.title(),
                 'snippet': doclines[-2]})
            self.print_guideline_error(**error_kwargs)

    def print_guideline_error(self, path, details, message, snippet=None):
        if isinstance(details, list):
            details = '.'.join(details)
        msg = _('ERROR (in %(path)s: %(details)s): %(message)s') % {
            'message': message,
            'path': path.replace('.', '/'),
            'details': details
        }
        if snippet is not None:
            msg = _('%(msg)s\n    (Error snippet): %(snippet)s') % {
                'msg': msg,
                'snippet': '%s...' % snippet[:79]
            }
        print(msg)
        self.error_count += 1


def _load_all_resources():
    manager = plugin_manager.PluginManager('heat.engine.resources')
    resource_mapping = plugin_manager.PluginMapping('resource')
    res_plugin_mappings = resource_mapping.load_all(manager)

    all_resources = {}
    for mapping in res_plugin_mappings:
        name, cls = mapping
        if all_resources.get(name) is not None:
            all_resources[name].append(cls)
        else:
            all_resources[name] = [cls]
    return all_resources


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exclude', '-e', metavar='<FOLDER>',
                        nargs='+',
                        help=_('Exclude specified paths from checking.'))
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    guidelines = HeatCustomGuidelines(args.exclude or [])
    guidelines.run_check()
