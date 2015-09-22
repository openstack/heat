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

from oslo_log import log as logging
import six
from stevedore import extension

from heat.common import exception
from heat.common.i18n import _
from heat.engine import environment
from heat.objects import raw_template as template_object

LOG = logging.getLogger(__name__)

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
    available_versions = list(six.iterkeys(_template_classes))
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
    """A stack template."""

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

        self.version = get_version(self.t,
                                   list(six.iterkeys(_template_classes)))
        self.t_digest = None

    def __deepcopy__(self, memo):
        return Template(copy.deepcopy(self.t, memo), files=self.files,
                        env=self.env)

    @classmethod
    def load(cls, context, template_id, t=None):
        """Retrieve a Template with the given ID from the database."""
        if t is None:
            t = template_object.RawTemplate.get_by_id(context, template_id)
        env = environment.Environment(t.environment)
        return cls(t.template, template_id=template_id, files=t.files, env=env)

    def store(self, context=None):
        """Store the Template in the database and return its ID."""
        rt = {
            'template': self.t,
            'files': self.files,
            'environment': self.env.user_env_as_dict()
        }
        if self.id is None:
            new_rt = template_object.RawTemplate.create(context, rt)
            self.id = new_rt.id
        else:
            template_object.RawTemplate.update_by_id(context, self.id, rt)
        return self.id

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

    @abc.abstractmethod
    def get_section_name(self, section):
        """Return a correct section name."""
        pass

    @abc.abstractmethod
    def parameters(self, stack_identifier, user_params, param_defaults=None):
        """Return a parameters.Parameters object for the stack."""
        pass

    @classmethod
    def validate_resource_key_type(cls, key, valid_types, typename,
                                   allowed_keys, rsrc_name, rsrc_data):
        """Validation type of the specific resource key.

        Used in validate_resource_definition and check correctness of
        key's type.
        """
        if key not in allowed_keys:
            raise ValueError(_('"%s" is not a valid '
                               'keyword inside a resource '
                               'definition') % key)
        if key in rsrc_data:
            if not isinstance(rsrc_data.get(key), valid_types):
                args = {'name': rsrc_name, 'key': key,
                        'typename': typename}
                message = _('Resource %(name)s %(key)s type '
                            'must be %(typename)s') % args
                raise TypeError(message)
            return True
        else:
            return False

    @abc.abstractmethod
    def validate_resource_definitions(self, stack):
        """Check section's type of ResourceDefinitions."""
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

    def remove_resource(self, name):
        """Remove a resource from the template."""
        self.t.get(self.RESOURCES, {}).pop(name)

    def parse(self, stack, snippet):
        return parse(self.functions, stack, snippet)

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
        # available in heat (http://specs.openstack.org/openstack/heat-specs/
        # specs/liberty/constraint-validation-cache.html). This is required
        # as multiple heat-engines may process the same template at least
        # in case of instance_group. And it fixes partially bug 1444316

        if t_digest == self.t_digest:
            return

        # check top-level sections
        for k in six.iterkeys(self.t):
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
                              version=('heat_template_version', '2015-04-30')):
        """Creates an empty template.

        Creates a new empty template with given version. If version is
        not provided, a new empty HOT template of version "2015-04-30"
        is returned.

        :param version: A tuple containing version header of the
        template: version key and value. E.g. ("heat_template_version",
        "2015-04-30")
        :returns: A new empty template.
        """
        tmpl = {version[0]: version[1]}
        return cls(tmpl)


def parse(functions, stack, snippet):
    recurse = functools.partial(parse, functions, stack)

    if isinstance(snippet, collections.Mapping):
        if len(snippet) == 1:
            fn_name, args = next(six.iteritems(snippet))
            Func = functions.get(fn_name)
            if Func is not None:
                return Func(stack, fn_name, recurse(args))
        return dict((k, recurse(v)) for k, v in six.iteritems(snippet))
    elif (not isinstance(snippet, six.string_types) and
          isinstance(snippet, collections.Iterable)):
        return [recurse(v) for v in snippet]
    else:
        return snippet
