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

import uuid

from heat.common import short_id
from heat.tests import common


class ShortIdTest(common.HeatTestCase):

    def test_byte_string_8(self):
        self.assertEqual(b'\xab', short_id._to_byte_string(0xab, 8))
        self.assertEqual(b'\x05', short_id._to_byte_string(0x05, 8))

    def test_byte_string_16(self):
        self.assertEqual(b'\xab\xcd', short_id._to_byte_string(0xabcd, 16))
        self.assertEqual(b'\x0a\xbc', short_id._to_byte_string(0xabc, 16))

    def test_byte_string_12(self):
        self.assertEqual(b'\xab\xc0', short_id._to_byte_string(0xabc, 12))
        self.assertEqual(b'\x0a\xb0', short_id._to_byte_string(0x0ab, 12))

    def test_byte_string_60(self):
        val = 0x111111111111111
        byte_string = short_id._to_byte_string(val, 60)
        self.assertEqual(b'\x11\x11\x11\x11\x11\x11\x11\x10', byte_string)

    def test_get_id_string(self):
        id = short_id.get_id('11111111-1111-4111-bfff-ffffffffffff')
        self.assertEqual('ceirceirceir', id)

    def test_get_id_uuid_1(self):
        source = uuid.UUID('11111111-1111-4111-bfff-ffffffffffff')
        self.assertEqual(0x111111111111111, source.time)
        self.assertEqual('ceirceirceir', short_id.get_id(source))

    def test_get_id_uuid_f(self):
        source = uuid.UUID('ffffffff-ffff-4fff-8000-000000000000')
        self.assertEqual('777777777777', short_id.get_id(source))

    def test_get_id_uuid_0(self):
        source = uuid.UUID('00000000-0000-4000-bfff-ffffffffffff')
        self.assertEqual('aaaaaaaaaaaa', short_id.get_id(source))

    def test_get_id_uuid_endianness(self):
        source = uuid.UUID('ffffffff-00ff-4000-aaaa-aaaaaaaaaaaa')
        self.assertEqual('aaaa77777777', short_id.get_id(source))

    def test_get_id_uuid1(self):
        source = uuid.uuid1()
        self.assertRaises(ValueError, short_id.get_id, source)

    def test_generate_ids(self):
        allowed_chars = [ord(c) for c in u'abcdefghijklmnopqrstuvwxyz234567']
        ids = [short_id.generate_id() for i in range(25)]

        for id in ids:
            self.assertEqual(12, len(id))
            self.assertFalse(id.translate({c: None for c in allowed_chars}))
            self.assertEqual(1, ids.count(id))
