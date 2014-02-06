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

from sqlalchemy.dialects.mysql.base import MySQLDialect
from sqlalchemy.dialects.sqlite.base import SQLiteDialect
from sqlalchemy import types
import testtools

from heat.db.sqlalchemy.types import Json
from heat.db.sqlalchemy.types import LongText


class LongTextTest(testtools.TestCase):

    def setUp(self):
        super(LongTextTest, self).setUp()
        self.sqltype = LongText()

    def test_load_dialect_impl(self):
        dialect = MySQLDialect()
        impl = self.sqltype.load_dialect_impl(dialect)
        self.assertNotEqual(types.Text, type(impl))
        dialect = SQLiteDialect()
        impl = self.sqltype.load_dialect_impl(dialect)
        self.assertEqual(types.Text, type(impl))


class JsonTest(testtools.TestCase):

    def setUp(self):
        super(JsonTest, self).setUp()
        self.sqltype = Json()

    def test_process_bind_param(self):
        dialect = None
        value = {'foo': 'bar'}
        result = self.sqltype.process_bind_param(value, dialect)
        self.assertEqual('{"foo": "bar"}', result)

    def test_process_result_value(self):
        dialect = None
        value = '{"foo": "bar"}'
        result = self.sqltype.process_result_value(value, dialect)
        self.assertEqual({'foo': 'bar'}, result)
