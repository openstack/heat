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

"""
APIs for dealing with input and output definitions for Software Configurations.
"""

import collections
import copy
import six

from heat.common.i18n import _

from heat.common import exception
from heat.engine import constraints
from heat.engine import parameters
from heat.engine import properties


(
    IO_NAME, DESCRIPTION, TYPE,
    DEFAULT, REPLACE_ON_CHANGE, VALUE,
    ERROR_OUTPUT,
) = (
    'name', 'description', 'type',
    'default', 'replace_on_change', 'value',
    'error_output',
)

TYPES = (
    STRING_TYPE, NUMBER_TYPE, LIST_TYPE, JSON_TYPE, BOOLEAN_TYPE,
) = (
    'String', 'Number', 'CommaDelimitedList', 'Json', 'Boolean',
)


input_config_schema = {
    IO_NAME: properties.Schema(
        properties.Schema.STRING,
        _('Name of the input.'),
        required=True
    ),
    DESCRIPTION: properties.Schema(
        properties.Schema.STRING,
        _('Description of the input.')
    ),
    TYPE: properties.Schema(
        properties.Schema.STRING,
        _('Type of the value of the input.'),
        default=STRING_TYPE,
        constraints=[constraints.AllowedValues(TYPES)]
    ),
    DEFAULT: properties.Schema(
        properties.Schema.ANY,
        _('Default value for the input if none is specified.'),
    ),
    REPLACE_ON_CHANGE: properties.Schema(
        properties.Schema.BOOLEAN,
        _('Replace the deployment instead of updating it when the input '
          'value changes.'),
        default=False,
    ),
}

output_config_schema = {
    IO_NAME: properties.Schema(
        properties.Schema.STRING,
        _('Name of the output.'),
        required=True
    ),
    DESCRIPTION: properties.Schema(
        properties.Schema.STRING,
        _('Description of the output.')
    ),
    TYPE: properties.Schema(
        properties.Schema.STRING,
        _('Type of the value of the output.'),
        default=STRING_TYPE,
        constraints=[constraints.AllowedValues(TYPES)]
    ),
    ERROR_OUTPUT: properties.Schema(
        properties.Schema.BOOLEAN,
        _('Denotes that the deployment is in an error state if this '
          'output has a value.'),
        default=False
    )
}


class IOConfig(object):
    """Base class for the configuration data for a single input or output."""
    def __init__(self, **config):
        self._props = properties.Properties(self.schema, config)
        try:
            self._props.validate()
        except exception.StackValidationFailed as exc:
            raise ValueError(six.text_type(exc))

    def name(self):
        """Return the name of the input or output."""
        return self._props[IO_NAME]

    def as_dict(self):
        """Return a dict representation suitable for persisting."""
        return {k: v for k, v in self._props.items() if v is not None}

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__,
                           ', '.join('%s=%s' % (k, repr(v))
                                     for k, v in self.as_dict().items()))


_no_value = object()


class InputConfig(IOConfig):
    """Class representing the configuration data for a single input."""
    schema = input_config_schema

    def __init__(self, value=_no_value, **config):
        if TYPE in config and DEFAULT in config:
            if config[DEFAULT] == '' and config[TYPE] != STRING_TYPE:
                # This is a legacy path, because default used to be of string
                # type, so we need to skip schema validation in this case.
                pass
            else:
                self.schema = copy.deepcopy(self.schema)
                config_param = parameters.Schema.from_dict(
                    'config', {'Type': config[TYPE]})
                self.schema[DEFAULT] = properties.Schema.from_parameter(
                    config_param)
        super(InputConfig, self).__init__(**config)
        self._value = value

    def default(self):
        """Return the default value of the input."""
        return self._props[DEFAULT]

    def replace_on_change(self):
        return self._props[REPLACE_ON_CHANGE]

    def as_dict(self):
        """Return a dict representation suitable for persisting."""
        d = super(InputConfig, self).as_dict()
        if not self._props[REPLACE_ON_CHANGE]:
            del d[REPLACE_ON_CHANGE]
        if self._value is not _no_value:
            d[VALUE] = self._value
        return d

    def input_data(self):
        """Return a name, value pair for the input."""
        value = self._value if self._value is not _no_value else None
        return self.name(), value


class OutputConfig(IOConfig):
    """Class representing the configuration data for a single output."""
    schema = output_config_schema

    def error_output(self):
        """Return True if the presence of the output indicates an error."""
        return self._props[ERROR_OUTPUT]


def check_io_schema_list(io_configs):
    """Check that an input or output schema list is of the correct type.

    Raises TypeError if the list itself is not a list, or if any of the
    members are not dicts.
    """
    if (not isinstance(io_configs, collections.Sequence) or
            isinstance(io_configs, collections.Mapping) or
            isinstance(io_configs, six.string_types)):
        raise TypeError('Software Config I/O Schema must be in a list')

    if not all(isinstance(conf, collections.Mapping) for conf in io_configs):
        raise TypeError('Software Config I/O Schema must be a dict')
