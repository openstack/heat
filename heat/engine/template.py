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
import hashlib

import six
from stevedore import extension

from heat.common import exception
from heat.common.i18n import _
from heat.common import template_format
from heat.engine import conditions
from heat.engine import environment
from heat.engine import function
from heat.engine import template_files
from heat.objects import raw_template as template_object

__all__ = ['Template']


_template_classes = None


def get_version(template_data, available_versions):
    version_keys = set(key for key, version in available_versions)
    candidate_keys = set(k for k, v in six.iteritems(template_data) if
                         isinstance(v, six.string_types))

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
        on_load_failure_callback=raise_extension_exception)


def raise_extension_exception(extmanager, ep, err):
    raise TemplatePluginNotRegistered(name=ep.name, error=six.text_type(err))


class TemplatePluginNotRegistered(exception.HeatException):
    msg_fmt = _("Could not load %(name)s: %(error)s")


def get_template_class(template_data):
    available_versions = _template_classes.keys()
    version = get_version(template_data, available_versions)
    version_type = version[0]
    try:
        return _template_classes[version]
    except KeyError:
        av_list = sorted(
            [v for k, v in available_versions if k == version_type])
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
    """Abstract base class for template format plugins.

    All template formats (both internal and third-party) should derive from
    Template and implement the abstract functions to provide resource
    definitions and other data.

    This is a stable third-party API. Do not add implementations that are
    specific to internal template formats. Do not add new abstract methods.
    """

    condition_functions = {}
    functions = {}

    def __new__(cls, template, *args, **kwargs):
        """Create a new Template of the appropriate class."""
        global _template_classes

        if _template_classes is None:
            mgr = _get_template_extension_manager()
            _template_classes = dict((tuple(name.split('.')), mgr[name].plugin)
                                     for name in mgr.names())

        if cls != Template:
            TemplateClass = cls
        else:
            TemplateClass = get_template_class(template)

        return super(Template, cls).__new__(TemplateClass)

    def __init__(self, template, template_id=None, files=None, env=None):
        """Initialise the template with JSON object and set of Parameters."""
        self.id = template_id
        self.t = template
        self.files = files or {}
        self.maps = self[self.MAPPINGS]
        self.env = env or environment.Environment({})
        self.merge_sections = [self.PARAMETERS]

        self.version = get_version(self.t, _template_classes.keys())
        self.t_digest = None

        condition_functions = {n: function.Invalid for n in self.functions}
        condition_functions.update(self.condition_functions)
        self._parser_condition_functions = condition_functions

    def __deepcopy__(self, memo):
        return Template(copy.deepcopy(self.t, memo), files=self.files,
                        env=self.env)

    def merge_snippets(self, other):
        for s in self.merge_sections:
            if s not in other.t:
                continue
            if s not in self.t:
                self.t[s] = {}
            self.t[s].update(other.t[s])

    @classmethod
    def load(cls, context, template_id, t=None):
        """Retrieve a Template with the given ID from the database."""
        if t is None:
            t = template_object.RawTemplate.get_by_id(context, template_id)
        env = environment.Environment(t.environment)
        # support loading the legacy t.files, but modern templates will
        # have a t.files_id
        t_files = t.files or t.files_id
        return cls(t.template, template_id=template_id, env=env,
                   files=t_files)

    def store(self, context):
        """Store the Template in the database and return its ID."""
        rt = {
            'template': self.t,
            'files_id': self.files.store(context),
            'environment': self.env.env_as_dict()
        }
        if self.id is None:
            new_rt = template_object.RawTemplate.create(context, rt)
            self.id = new_rt.id
        else:
            template_object.RawTemplate.update_by_id(context, self.id, rt)
        return self.id

    @property
    def files(self):
        return self._template_files

    @files.setter
    def files(self, files):
        self._template_files = template_files.TemplateFiles(files)

    def __iter__(self):
        """Return an iterator over the section names."""
        return (s for s in self.SECTIONS
                if s not in self.SECTIONS_NO_DIRECT_ACCESS)

    def __len__(self):
        """Return the number of sections."""
        return len(self.SECTIONS) - len(self.SECTIONS_NO_DIRECT_ACCESS)

    @abc.abstractmethod
    def param_schemata(self, param_defaults=None):
        """Return a dict of parameters.Schema objects for the parameters."""
        pass

    def all_param_schemata(self, files):
        schema = {}
        files = files if files is not None else {}
        for f in files.values():
            try:
                data = template_format.parse(f)
            except ValueError:
                continue
            else:
                sub_tmpl = Template(data)
                schema.update(sub_tmpl.param_schemata())
        # Parent template has precedence, so update the schema last.
        schema.update(self.param_schemata())
        return schema

    @abc.abstractmethod
    def get_section_name(self, section):
        """Get the name of a field within a resource or output definition.

        Return the name of the given field (specified by the constants given
        in heat.engine.rsrc_defn and heat.engine.output) in the template
        format. This is used in error reporting to help users find the
        location of errors in the template.

        Note that 'section' here does not refer to a top-level section of the
        template (like parameters, resources, &c.) as it does everywhere else.
        """
        pass

    @abc.abstractmethod
    def parameters(self, stack_identifier, user_params, param_defaults=None):
        """Return a parameters.Parameters object for the stack."""
        pass

    def validate_resource_definitions(self, stack):
        """Check validity of resource definitions.

        This method is deprecated. Subclasses should validate the resource
        definitions in the process of generating them when calling
        resource_definitions(). However, for now this method is still called
        in case any third-party plugins are relying on this for validation and
        need time to migrate.
        """
        pass

    def conditions(self, stack):
        """Return a dictionary of resolved conditions."""
        return conditions.Conditions({})

    @abc.abstractmethod
    def outputs(self, stack):
        """Return a dictionary of OutputDefinition objects."""
        pass

    @abc.abstractmethod
    def resource_definitions(self, stack):
        """Return a dictionary of ResourceDefinition objects."""
        pass

    @abc.abstractmethod
    def add_resource(self, definition, name=None):
        """Add a resource to the template.

        The resource is passed as a ResourceDefinition object. If no name is
        specified, the name from the ResourceDefinition should be used.
        """
        pass

    def add_output(self, definition):
        """Add an output to the template.

        The output is passed as a OutputDefinition object.
        """
        raise NotImplementedError

    def remove_resource(self, name):
        """Remove a resource from the template."""
        self.t.get(self.RESOURCES, {}).pop(name)

    def remove_all_resources(self):
        """Remove all the resources from the template."""
        if self.RESOURCES in self.t:
            self.t.update({self.RESOURCES: {}})

    def parse(self, stack, snippet, path=''):
        return parse(self.functions, stack, snippet, path, self)

    def parse_condition(self, stack, snippet, path=''):
        return parse(self._parser_condition_functions, stack, snippet,
                     path, self)

    def validate(self):
        """Validate the template.

        Validates the top-level sections of the template as well as syntax
        inside select sections. Some sections are not checked here but in
        code parts that are responsible for working with the respective
        sections (e.g. parameters are check by parameters schema class).
        """
        t_digest = hashlib.sha256(
            six.text_type(self.t).encode('utf-8')).hexdigest()

        # TODO(kanagaraj-manickam) currently t_digest is stored in self. which
        # is used to check whether already template is validated or not.
        # But it needs to be loaded from dogpile cache backend once its
        # available in heat (https://specs.openstack.org/openstack/heat-specs/
        # specs/liberty/constraint-validation-cache.html). This is required
        # as multiple heat-engines may process the same template at least
        # in case of instance_group. And it fixes partially bug 1444316

        if t_digest == self.t_digest:
            return

        # check top-level sections
        for k in self.t.keys():
            if k not in self.SECTIONS:
                raise exception.InvalidTemplateSection(section=k)

        # check resources
        for res in six.itervalues(self[self.RESOURCES]):
            try:
                if not res or not res.get('Type'):
                    message = _('Each Resource must contain '
                                'a Type key.')
                    raise exception.StackValidationFailed(message=message)
            except AttributeError:
                message = _('Resources must contain Resource. '
                            'Found a [%s] instead') % type(res)
                raise exception.StackValidationFailed(message=message)
        self.t_digest = t_digest

    @classmethod
    def create_empty_template(cls,
                              version=('heat_template_version', '2015-04-30'),
                              from_template=None):
        """Create an empty template.

        Creates a new empty template with given version. If version is
        not provided, a new empty HOT template of version "2015-04-30"
        is returned.

        :param version: A tuple containing version header of the template
                        version key and value,
                        e.g. ``('heat_template_version', '2015-04-30')``
        :returns: A new empty template.
        """
        if from_template:
            # remove resources from the template and return; keep the
            # env and other things intact
            tmpl = copy.deepcopy(from_template)
            tmpl.remove_all_resources()
            return tmpl
        else:
            tmpl = {version[0]: version[1]}
            return cls(tmpl)


def parse(functions, stack, snippet, path='', template=None):
    recurse = functools.partial(parse, functions, stack, template=template)

    if isinstance(snippet, collections.Mapping):
        def mkpath(key):
            return '.'.join([path, six.text_type(key)])

        if len(snippet) == 1:
            fn_name, args = next(six.iteritems(snippet))
            Func = functions.get(fn_name)
            if Func is not None:
                try:
                    path = '.'.join([path, fn_name])
                    if (isinstance(Func, type) and
                            issubclass(Func, function.Macro)):
                        return Func(stack, fn_name, args,
                                    functools.partial(recurse, path=path),
                                    template)
                    else:
                        return Func(stack, fn_name, recurse(args, path))
                except (ValueError, TypeError, KeyError) as e:
                    raise exception.StackValidationFailed(
                        path=path,
                        message=six.text_type(e))

        return dict((k, recurse(v, mkpath(k)))
                    for k, v in six.iteritems(snippet))
    elif (not isinstance(snippet, six.string_types) and
          isinstance(snippet, collections.Iterable)):

        def mkpath(idx):
            return ''.join([path, '[%d]' % idx])

        return [recurse(v, mkpath(i)) for i, v in enumerate(snippet)]
    else:
        return snippet
