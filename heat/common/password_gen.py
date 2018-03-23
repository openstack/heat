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

import collections
import random as random_module
import string

import six


# NOTE(pas-ha) Heat officially supports only POSIX::Linux platform
# where os.urandom() and random.SystemRandom() are available
random = random_module.SystemRandom()


CHARACTER_CLASSES = (
    LETTERS_DIGITS, LETTERS, LOWERCASE, UPPERCASE,
    DIGITS, HEXDIGITS, OCTDIGITS,
) = (
    'lettersdigits', 'letters', 'lowercase', 'uppercase',
    'digits', 'hexdigits', 'octdigits',
)

_char_class_members = {
    LETTERS_DIGITS: string.ascii_letters + string.digits,
    LETTERS: string.ascii_letters,
    LOWERCASE: string.ascii_lowercase,
    UPPERCASE: string.ascii_uppercase,
    DIGITS: string.digits,
    HEXDIGITS: string.digits + 'ABCDEF',
    OCTDIGITS: string.octdigits,
}


CharClass = collections.namedtuple('CharClass',
                                   ('allowed_chars', 'min_count'))


def named_char_class(char_class, min_count=0):
    """Return a predefined character class.

    The result of this function can be passed to :func:`generate_password` as
    one of the character classes to use in generating a password.

    :param char_class: Any of the character classes named in
                       :const:`CHARACTER_CLASSES`
    :param min_count: The minimum number of members of this class to appear in
                      a generated password
    """
    assert char_class in CHARACTER_CLASSES
    return CharClass(frozenset(_char_class_members[char_class]), min_count)


def special_char_class(allowed_chars, min_count=0):
    """Return a character class containing custom characters.

    The result of this function can be passed to :func:`generate_password` as
    one of the character classes to use in generating a password.

    :param allowed_chars: Iterable of the characters in the character class
    :param min_count: The minimum number of members of this class to appear in
                      a generated password
    """
    return CharClass(frozenset(allowed_chars), min_count)


def generate_password(length, char_classes):
    """Generate a random password.

    The password will be of the specified length, and comprised of characters
    from the specified character classes, which can be generated using the
    :func:`named_char_class` and :func:`special_char_class` functions. Where
    a minimum count is specified in the character class, at least that number
    of characters in the resulting password are guaranteed to be from that
    character class.

    :param length: The length of the password to generate, in characters
    :param char_classes: Iterable over classes of characters from which to
                         generate a password
    """
    char_buffer = six.StringIO()
    all_allowed_chars = set()

    # Add the minimum number of chars from each char class
    for char_class in char_classes:
        all_allowed_chars |= char_class.allowed_chars
        allowed_chars = tuple(char_class.allowed_chars)
        for i in six.moves.xrange(char_class.min_count):
            char_buffer.write(random.choice(allowed_chars))

    # Fill up rest with random chars from provided classes
    combined_chars = tuple(all_allowed_chars)
    for i in six.moves.xrange(max(0, length - char_buffer.tell())):
        char_buffer.write(random.choice(combined_chars))

    # Shuffle string
    selected_chars = char_buffer.getvalue()
    char_buffer.close()
    return ''.join(random.sample(selected_chars, length))


def generate_openstack_password():
    """Generate a random password suitable for a Keystone User."""
    return generate_password(32, [named_char_class(LOWERCASE, 1),
                                  named_char_class(UPPERCASE, 1),
                                  named_char_class(DIGITS, 1),
                                  special_char_class('!@#%^&*', 1)])
