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

import random
import string

from six.moves import xrange

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class RandomString(resource.Resource):
    '''
    A resource which generates a random string.

    This is useful for configuring passwords and secrets on services.
    '''
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
                constraints.AllowedValues(['lettersdigits', 'letters',
                                           'lowercase', 'uppercase',
                                           'digits', 'hexdigits',
                                           'octdigits']),
            ],
            support_status=support.SupportStatus(
                support.DEPRECATED,
                _('Use property %s.') % CHARACTER_CLASSES
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
                                ['lettersdigits', 'letters', 'lowercase',
                                 'uppercase', 'digits', 'hexdigits',
                                 'octdigits']),
                        ],
                        default='lettersdigits'),
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
            )
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
              'the resource for replacement with a new random string . The '
              'salt value itself is ignored by the random generator.')
        ),
    }

    attributes_schema = {
        VALUE: attributes.Schema(
            _('The random string generated by this resource. This value is '
              'also available by referencing the resource.'),
            cache_mode=attributes.Schema.CACHE_NONE
        ),
    }

    _sequences = {
        'lettersdigits': string.ascii_letters + string.digits,
        'letters': string.ascii_letters,
        'lowercase': string.ascii_lowercase,
        'uppercase': string.ascii_uppercase,
        'digits': string.digits,
        'hexdigits': string.digits + 'ABCDEF',
        'octdigits': string.octdigits
    }

    @staticmethod
    def _deprecated_random_string(sequence, length):
        rand = random.SystemRandom()
        return ''.join(rand.choice(sequence) for x in xrange(length))

    def _generate_random_string(self, char_sequences, char_classes, length):
        random_string = ""

        # Add the minimum number of chars from each char sequence & char class
        if char_sequences:
            for char_seq in char_sequences:
                seq = char_seq[self.CHARACTER_SEQUENCES_SEQUENCE]
                seq_min = char_seq[self.CHARACTER_SEQUENCES_MIN]
                for _ in xrange(seq_min):
                    random_string += random.choice(seq)

        if char_classes:
            for char_class in char_classes:
                cclass_class = char_class[self.CHARACTER_CLASSES_CLASS]
                cclass_seq = self._sequences[cclass_class]
                cclass_min = char_class[self.CHARACTER_CLASSES_MIN]
                for _ in xrange(cclass_min):
                    random_string += random.choice(cclass_seq)

        def random_class_char():
            cclass_dict = random.choice(char_classes)
            cclass_class = cclass_dict[self.CHARACTER_CLASSES_CLASS]
            cclass_seq = self._sequences[cclass_class]
            return random.choice(cclass_seq)

        def random_seq_char():
            seq_dict = random.choice(char_sequences)
            seq = seq_dict[self.CHARACTER_SEQUENCES_SEQUENCE]
            return random.choice(seq)

        # Fill up rest with random chars from provided sequences & classes
        if char_sequences and char_classes:
            weighted_choices = ([True] * len(char_classes) +
                                [False] * len(char_sequences))
            while len(random_string) < length:
                if random.choice(weighted_choices):
                    random_string += random_class_char()
                else:
                    random_string += random_seq_char()

        elif char_sequences:
            while len(random_string) < length:
                random_string += random_seq_char()

        else:
            while len(random_string) < length:
                random_string += random_class_char()

        # Randomize string
        random_string = ''.join(random.sample(random_string,
                                              len(random_string)))
        return random_string

    def validate(self):
        super(RandomString, self).validate()
        sequence = self.properties.get(self.SEQUENCE)
        char_sequences = self.properties.get(self.CHARACTER_SEQUENCES)
        char_classes = self.properties.get(self.CHARACTER_CLASSES)

        if sequence and (char_sequences or char_classes):
            msg = (_("Cannot use deprecated '%(seq)s' property along with "
                     "'%(char_seqs)s' or '%(char_classes)s' properties")
                   % {'seq': self.SEQUENCE,
                      'char_seqs': self.CHARACTER_SEQUENCES,
                      'char_classes': self.CHARACTER_CLASSES})
            raise exception.StackValidationFailed(message=msg)

        def char_min(char_dicts, min_prop):
            if char_dicts:
                return sum(char_dict[min_prop] for char_dict in char_dicts)
            return 0

        length = self.properties.get(self.LENGTH)
        min_length = (char_min(char_sequences, self.CHARACTER_SEQUENCES_MIN) +
                      char_min(char_classes, self.CHARACTER_CLASSES_MIN))
        if min_length > length:
            msg = _("Length property cannot be smaller than combined "
                    "character class and character sequence minimums")
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        char_sequences = self.properties.get(self.CHARACTER_SEQUENCES)
        char_classes = self.properties.get(self.CHARACTER_CLASSES)
        length = self.properties.get(self.LENGTH)

        if char_sequences or char_classes:
            random_string = self._generate_random_string(char_sequences,
                                                         char_classes,
                                                         length)
        else:
            sequence = self.properties.get(self.SEQUENCE)
            if not sequence:  # Deprecated property not provided, use a default
                sequence = "lettersdigits"

            char_seq = self._sequences[sequence]
            random_string = self._deprecated_random_string(char_seq, length)

        self.data_set('value', random_string, redact=True)
        self.resource_id_set(random_string)

    def _resolve_attribute(self, name):
        if name == self.VALUE:
            return self.data().get(self.VALUE)


def resource_mapping():
    return {
        'OS::Heat::RandomString': RandomString,
    }
