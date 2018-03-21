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

import six

from heat.common import exception
from heat.common.i18n import _
from heat.common import password_gen
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import translation


class RandomString(resource.Resource):
    """A resource which generates a random string.

    This is useful for configuring passwords and secrets on services. Random
    string can be generated from specified character sequences, which means
    that all characters will be randomly chosen from specified sequences, or
    with some classes, e.g. letterdigits, which means that all character will
    be randomly chosen from union of ascii letters and digits. Output string
    will be randomly generated string with specified length (or with length of
    32, if length property doesn't specified).
    """

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        LENGTH, SEQUENCE, CHARACTER_CLASSES, CHARACTER_SEQUENCES,
        SALT,
    ) = (
        'length', 'sequence', 'character_classes', 'character_sequences',
        'salt',
    )

    _CHARACTER_CLASSES_KEYS = (
        CHARACTER_CLASSES_CLASS, CHARACTER_CLASSES_MIN,
    ) = (
        'class', 'min',
    )

    _CHARACTER_SEQUENCES = (
        CHARACTER_SEQUENCES_SEQUENCE, CHARACTER_SEQUENCES_MIN,
    ) = (
        'sequence', 'min',
    )

    ATTRIBUTES = (
        VALUE,
    ) = (
        'value',
    )

    properties_schema = {
        LENGTH: properties.Schema(
            properties.Schema.INTEGER,
            _('Length of the string to generate.'),
            default=32,
            constraints=[
                constraints.Range(1, 512),
            ]
        ),
        SEQUENCE: properties.Schema(
            properties.Schema.STRING,
            _('Sequence of characters to build the random string from.'),
            constraints=[
                constraints.AllowedValues(password_gen.CHARACTER_CLASSES),
            ],
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='5.0.0',
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    message=_('Use property %s.') % CHARACTER_CLASSES,
                    version='2014.2'
                )
            )
        ),
        CHARACTER_CLASSES: properties.Schema(
            properties.Schema.LIST,
            _('A list of character class and their constraints to generate '
              'the random string from.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    CHARACTER_CLASSES_CLASS: properties.Schema(
                        properties.Schema.STRING,
                        (_('A character class and its corresponding %(min)s '
                           'constraint to generate the random string from.')
                         % {'min': CHARACTER_CLASSES_MIN}),
                        constraints=[
                            constraints.AllowedValues(
                                password_gen.CHARACTER_CLASSES),
                        ],
                        default=password_gen.LETTERS_DIGITS),
                    CHARACTER_CLASSES_MIN: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The minimum number of characters from this '
                          'character class that will be in the generated '
                          'string.'),
                        default=1,
                        constraints=[
                            constraints.Range(1, 512),
                        ]
                    )
                }
            ),
            # add defaults for backward compatibility
            default=[{CHARACTER_CLASSES_CLASS: password_gen.LETTERS_DIGITS,
                      CHARACTER_CLASSES_MIN: 1}]

        ),
        CHARACTER_SEQUENCES: properties.Schema(
            properties.Schema.LIST,
            _('A list of character sequences and their constraints to '
              'generate the random string from.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    CHARACTER_SEQUENCES_SEQUENCE: properties.Schema(
                        properties.Schema.STRING,
                        _('A character sequence and its corresponding %(min)s '
                          'constraint to generate the random string '
                          'from.') % {'min': CHARACTER_SEQUENCES_MIN},
                        required=True),
                    CHARACTER_SEQUENCES_MIN: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The minimum number of characters from this '
                          'sequence that will be in the generated '
                          'string.'),
                        default=1,
                        constraints=[
                            constraints.Range(1, 512),
                        ]
                    )
                }
            )
        ),
        SALT: properties.Schema(
            properties.Schema.STRING,
            _('Value which can be set or changed on stack update to trigger '
              'the resource for replacement with a new random string. The '
              'salt value itself is ignored by the random generator.')
        ),
    }

    attributes_schema = {
        VALUE: attributes.Schema(
            _('The random string generated by this resource. This value is '
              'also available by referencing the resource.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
    }

    def translation_rules(self, props):
        if props.get(self.SEQUENCE):
            return [
                translation.TranslationRule(
                    props,
                    translation.TranslationRule.ADD,
                    [self.CHARACTER_CLASSES],
                    [{self.CHARACTER_CLASSES_CLASS: props.get(
                        self.SEQUENCE),
                        self.CHARACTER_CLASSES_MIN: 1}]),
                translation.TranslationRule(
                    props,
                    translation.TranslationRule.DELETE,
                    [self.SEQUENCE]
                )
            ]

    def _generate_random_string(self, char_sequences, char_classes, length):
        seq_mins = [
            password_gen.special_char_class(
                char_seq[self.CHARACTER_SEQUENCES_SEQUENCE],
                char_seq[self.CHARACTER_SEQUENCES_MIN])
            for char_seq in char_sequences]
        char_class_mins = [
            password_gen.named_char_class(
                char_class[self.CHARACTER_CLASSES_CLASS],
                char_class[self.CHARACTER_CLASSES_MIN])
            for char_class in char_classes]

        return password_gen.generate_password(length,
                                              seq_mins + char_class_mins)

    def validate(self):
        super(RandomString, self).validate()
        char_sequences = self.properties[self.CHARACTER_SEQUENCES]
        char_classes = self.properties[self.CHARACTER_CLASSES]

        def char_min(char_dicts, min_prop):
            if char_dicts:
                return sum(char_dict[min_prop] for char_dict in char_dicts)
            return 0

        length = self.properties[self.LENGTH]
        min_length = (char_min(char_sequences, self.CHARACTER_SEQUENCES_MIN) +
                      char_min(char_classes, self.CHARACTER_CLASSES_MIN))
        if min_length > length:
            msg = _("Length property cannot be smaller than combined "
                    "character class and character sequence minimums")
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        char_sequences = self.properties[self.CHARACTER_SEQUENCES] or []
        char_classes = self.properties[self.CHARACTER_CLASSES] or []
        length = self.properties[self.LENGTH]

        random_string = self._generate_random_string(char_sequences,
                                                     char_classes,
                                                     length)
        self.data_set('value', random_string, redact=True)
        self.resource_id_set(self.physical_resource_name())

    def _resolve_attribute(self, name):
        if name == self.VALUE:
            return self.data().get(self.VALUE)

    def get_reference_id(self):
        if self.resource_id is not None:
            return self.data().get('value')
        else:
            return six.text_type(self.name)


def resource_mapping():
    return {
        'OS::Heat::RandomString': RandomString,
    }
