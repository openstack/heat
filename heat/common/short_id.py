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

"""Utilities for creating short ID strings based on a random UUID.

The IDs each comprise 12 (lower-case) alphanumeric characters.
"""

import base64
import uuid

import six

from heat.common.i18n import _


def _to_byte_string(value, num_bits):
    """Convert an integer to a big-endian string of bytes with padding.

    Padding is added at the end (i.e. after the least-significant bit) if
    required.
    """
    shifts = six.moves.xrange(num_bits - 8, -8, -8)

    def byte_at(off):
        return (value >> off if off >= 0 else value << -off) & 0xff

    return b''.join(six.int2byte(byte_at(offset)) for offset in shifts)


def get_id(source_uuid):
    """Derive a short (12 character) id from a random UUID.

    The supplied UUID must be a version 4 UUID object.
    """
    if isinstance(source_uuid, six.string_types):
        source_uuid = uuid.UUID(source_uuid)
    if source_uuid.version != 4:
        raise ValueError(_('Invalid UUID version (%d)') % source_uuid.version)

    # The "time" field of a v4 UUID contains 60 random bits
    # (see RFC4122, Section 4.4)
    random_bytes = _to_byte_string(source_uuid.time, 60)
    # The first 12 bytes (= 60 bits) of base32-encoded output is our data

    encoded_bytes = base64.b32encode(random_bytes)[:12]
    return encoded_bytes.decode('ascii').lower()


def generate_id():
    """Generate a short (12 character), random id."""
    return get_id(uuid.uuid4())
