
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

import abc
import collections
import functools

from heat.db import api as db_api
from heat.common import exception
from heat.engine import plugin_manager


__all__ = ['Template']


DEFAULT_VERSION = ('HeatTemplateFormatVersion', '2012-12-12')

_template_classes = None


class TemplatePluginManager(object):
    '''A Descriptor class for caching PluginManagers.

    Keeps a cache of PluginManagers with the search directories corresponding
    to the package containing the owner class.
    '''

    def __init__(self):
        self.plugin_managers = {}

    @staticmethod
    def package_name(obj_class):
        '''Return the package containing the given class.'''
        module_name = obj_class.__module__
        return module_name.rsplit('.', 1)[0]

    def __get__(self, obj, obj_class):
        '''Get a PluginManager for a class.'''
        pkg = self.package_name(obj_class)
        if pkg not in self.plugin_managers:
            self.plugin_managers[pkg] = plugin_manager.PluginManager(pkg)

        return self.plugin_managers[pkg]


def get_version(template_data, available_versions):
    version_keys = set(key for key, version in available_versions)
    candidate_keys = set(k for k, v in template_data.iteritems() if
                         isinstance(v, basestring))

    keys_present = version_keys & candidate_keys
    if not keys_present:
        return DEFAULT_VERSION

    if len(keys_present) > 1:
        explanation = _('Ambiguous versions (%s)') % ', '.join(keys_present)
        raise exception.InvalidTemplateVersion(explanation=explanation)

    version_key = keys_present.pop()
    return version_key, template_data[version_key]


def get_template_class(plugin_mgr, template_data):
    global _template_classes

    if _template_classes is None:
        tmpl_mapping = plugin_manager.PluginMapping('template')
        _template_classes = dict(tmpl_mapping.load_all(plugin_mgr))

    available_versions = _template_classes.keys()
    version = get_version(template_data, available_versions)
    try:
        return _template_classes[version]
    except KeyError:
        msg_data = {'version': ': '.join(version),
                    'available': ', '.join(v for vk, v in available_versions)}
        explanation = _('Unknown version (%(version)s). '
                        'Should be one of: %(available)s') % msg_data
        raise exception.InvalidTemplateVersion(explanation=explanation)


class Template(collections.Mapping):
    '''A stack template.'''

    _plugins = TemplatePluginManager()
    _functionmaps = {}

    def __new__(cls, template, *args, **kwargs):
        '''Create a new Template of the appropriate class.'''

        if cls != Template:
            TemplateClass = cls
        else:
            TemplateClass = get_template_class(cls._plugins, template)

        return super(Template, cls).__new__(TemplateClass)

    def __init__(self, template, template_id=None, files=None):
        '''
        Initialise the template with a JSON object and a set of Parameters
        '''
        self.id = template_id
        self.t = template
        self.files = files or {}
        self.maps = self[self.MAPPINGS]
        self.version = get_version(self.t, _template_classes.keys())

    @classmethod
    def load(cls, context, template_id):
        '''Retrieve a Template with the given ID from the database.'''
        t = db_api.raw_template_get(context, template_id)
        return cls(t.template, template_id=template_id, files=t.files)

    def store(self, context=None):
        '''Store the Template in the database and return its ID.'''
        if self.id is None:
            rt = {
                'template': self.t,
                'files': self.files
            }
            new_rt = db_api.raw_template_create(context, rt)
            self.id = new_rt.id
        return self.id

    def __iter__(self):
        '''Return an iterator over the section names.'''
        return (s for s in self.SECTIONS
                if s not in self.SECTIONS_NO_DIRECT_ACCESS)

    def __len__(self):
        '''Return the number of sections.'''
        return len(self.SECTIONS) - len(self.SECTIONS_NO_DIRECT_ACCESS)

    @abc.abstractmethod
    def param_schemata(self):
        '''Return a dict of parameters.Schema objects for the parameters.'''
        pass

    @abc.abstractmethod
    def parameters(self, stack_identifier, user_params):
        '''Return a parameters.Parameters object for the stack.'''
        pass

    def functions(self):
        '''Return a dict of template functions keyed by name.'''
        if self.version not in self._functionmaps:
            mappings = plugin_manager.PluginMapping('function', *self.version)
            funcs = dict(mappings.load_all(self._plugins))
            self._functionmaps[self.version] = funcs

        return self._functionmaps[self.version]

    def parse(self, stack, snippet):
        return parse(self.functions(), stack, snippet)

    def validate(self):
        '''Validate the template.

        Only validates the top-level sections of the template. Syntax inside
        sections is not checked here but in code parts that are responsible
        for working with the respective sections.
        '''

        for k in self.t.keys():
            if k not in self.SECTIONS:
                raise exception.InvalidTemplateSection(section=k)


def parse(functions, stack, snippet):
    recurse = functools.partial(parse, functions, stack)

    if isinstance(snippet, collections.Mapping):
        if len(snippet) == 1:
            fn_name, args = next(snippet.iteritems())
            Func = functions.get(fn_name)
            if Func is not None:
                return Func(stack, fn_name, recurse(args))
        return dict((k, recurse(v)) for k, v in snippet.iteritems())
    elif (not isinstance(snippet, basestring) and
          isinstance(snippet, collections.Iterable)):
        return [recurse(v) for v in snippet]
    else:
        return snippet
