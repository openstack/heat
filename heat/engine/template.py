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
import copy
import functools
import six
from stevedore import extension

from heat.common import exception
from heat.db import api as db_api
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)

__all__ = ['Template']


_template_classes = None


def get_version(template_data, available_versions):
    version_keys = set(key for key, version in available_versions)
    candidate_keys = set(k for k, v in six.iteritems(template_data) if
                         isinstance(v, basestring))

    keys_present = version_keys & candidate_keys

    if len(keys_present) > 1:
        explanation = _('Ambiguous versions (%s)') % ', '.join(keys_present)
        raise exception.InvalidTemplateVersion(explanation=explanation)
    try:
        version_key = keys_present.pop()
    except KeyError:
        explanation = _('Template version was not provided')
        raise exception.InvalidTemplateVersion(explanation=explanation)
    return version_key, template_data[version_key]


def _get_template_extension_manager():
    return extension.ExtensionManager(
        namespace='heat.templates',
        invoke_on_load=False,
        verify_requirements=True)


def get_template_class(template_data):
    global _template_classes

    if _template_classes is None:
        mgr = _get_template_extension_manager()
        _template_classes = dict((tuple(name.split('.')), mgr[name].plugin)
                                 for name in mgr.names())

    available_versions = _template_classes.keys()
    version = get_version(template_data, available_versions)
    version_type = version[0]
    try:
        return _template_classes[version]
    except KeyError:
        av_list = [v for k, v in available_versions if k == version_type]
        msg_data = {'version': ': '.join(version),
                    'version_type': version_type,
                    'available': ', '.join(v for v in av_list)}

        if len(av_list) > 1:
            explanation = _('"%(version)s". "%(version_type)s" '
                            'should be one of: %(available)s') % msg_data
        else:
            explanation = _('"%(version)s". "%(version_type)s" '
                            'should be: %(available)s') % msg_data
        raise exception.InvalidTemplateVersion(explanation=explanation)


class Template(collections.Mapping):
    '''A stack template.'''

    def __new__(cls, template, *args, **kwargs):
        '''Create a new Template of the appropriate class.'''

        if cls != Template:
            TemplateClass = cls
        else:
            TemplateClass = get_template_class(template)

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

    def __deepcopy__(self, memo):
        return Template(copy.deepcopy(self.t, memo), files=self.files)

    @classmethod
    def load(cls, context, template_id, t=None):
        '''Retrieve a Template with the given ID from the database.'''
        if t is None:
            t = db_api.raw_template_get(context, template_id)
        return cls(t.template, template_id=template_id, files=t.files)

    def store(self, context=None):
        '''Store the Template in the database and return its ID.'''
        rt = {
            'template': self.t,
            'files': self.files
        }
        if self.id is None:
            new_rt = db_api.raw_template_create(context, rt)
            self.id = new_rt.id
        else:
            db_api.raw_template_update(context, self.id, rt)
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

    @abc.abstractmethod
    def resource_definitions(self, stack):
        '''Return a dictionary of ResourceDefinition objects.'''
        pass

    @abc.abstractmethod
    def add_resource(self, definition, name=None):
        '''Add a resource to the template.

        The resource is passed as a ResourceDefinition object. If no name is
        specified, the name from the ResourceDefinition should be used.
        '''
        pass

    def remove_resource(self, name):
        '''Remove a resource from the template.'''
        self.t.get(self.RESOURCES, {}).pop(name)

    def parse(self, stack, snippet):
        return parse(self.functions, stack, snippet)

    def validate(self):
        '''Validate the template.

        Validates the top-level sections of the template as well as syntax
        inside select sections. Some sections are not checked here but in
        code parts that are responsible for working with the respective
        sections (e.g. parameters are check by parameters schema class).

        '''

        # check top-level sections
        for k in self.t.keys():
            if k not in self.SECTIONS:
                raise exception.InvalidTemplateSection(section=k)

        # check resources
        for res in self[self.RESOURCES].values():
            try:
                if not res.get('Type'):
                    message = _('Every Resource object must '
                                'contain a Type member.')
                    raise exception.StackValidationFailed(message=message)
            except AttributeError:
                type_res = type(res)
                if isinstance(res, unicode):
                    type_res = "string"
                message = _('Resources must contain Resource. '
                            'Found a [%s] instead') % type_res
                raise exception.StackValidationFailed(message=message)


def parse(functions, stack, snippet):
    recurse = functools.partial(parse, functions, stack)

    if isinstance(snippet, collections.Mapping):
        if len(snippet) == 1:
            fn_name, args = next(six.iteritems(snippet))
            Func = functions.get(fn_name)
            if Func is not None:
                return Func(stack, fn_name, recurse(args))
        return dict((k, recurse(v)) for k, v in six.iteritems(snippet))
    elif (not isinstance(snippet, basestring) and
          isinstance(snippet, collections.Iterable)):
        return [recurse(v) for v in snippet]
    else:
        return snippet
