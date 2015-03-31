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

from sqlalchemy.dialects.mysql import base as mysql_base
from sqlalchemy.dialects.sqlite import base as sqlite_base
from sqlalchemy import types

from heat.db.sqlalchemy import types as db_types
from heat.tests import common


class LongTextTest(common.HeatTestCase):

    def setUp(self):
        super(LongTextTest, self).setUp()
        self.sqltype = db_types.LongText()

    def test_load_dialect_impl(self):
        dialect = mysql_base.MySQLDialect()
        impl = self.sqltype.load_dialect_impl(dialect)
        self.assertNotEqual(types.Text, type(impl))
        dialect = sqlite_base.SQLiteDialect()
        impl = self.sqltype.load_dialect_impl(dialect)
        self.assertEqual(types.Text, type(impl))


class JsonTest(common.HeatTestCase):

    def setUp(self):
        super(JsonTest, self).setUp()
        self.sqltype = db_types.Json()

    def test_process_bind_param(self):
        dialect = None
        value = {'foo': 'bar'}
        result = self.sqltype.process_bind_param(value, dialect)
        self.assertEqual('{"foo": "bar"}', result)

    def test_process_bind_param_null(self):
        dialect = None
        value = None
        result = self.sqltype.process_bind_param(value, dialect)
        self.assertEqual('null', result)

    def test_process_result_value(self):
        dialect = None
        value = '{"foo": "bar"}'
        result = self.sqltype.process_result_value(value, dialect)
        self.assertEqual({'foo': 'bar'}, result)

    def test_process_result_value_null(self):
        dialect = None
        value = None
        result = self.sqltype.process_result_value(value, dialect)
        self.assertIsNone(result)


class ListTest(common.HeatTestCase):

    def setUp(self):
        super(ListTest, self).setUp()
        self.sqltype = db_types.List()

    def test_load_dialect_impl(self):
        dialect = mysql_base.MySQLDialect()
        impl = self.sqltype.load_dialect_impl(dialect)
        self.assertNotEqual(types.Text, type(impl))
        dialect = sqlite_base.SQLiteDialect()
        impl = self.sqltype.load_dialect_impl(dialect)
        self.assertEqual(types.Text, type(impl))

    def test_process_bind_param(self):
        dialect = None
        value = ['foo', 'bar']
        result = self.sqltype.process_bind_param(value, dialect)
        self.assertEqual('["foo", "bar"]', result)

    def test_process_bind_param_null(self):
        dialect = None
        value = None
        result = self.sqltype.process_bind_param(value, dialect)
        self.assertEqual('null', result)

    def test_process_result_value(self):
        dialect = None
        value = '["foo", "bar"]'
        result = self.sqltype.process_result_value(value, dialect)
        self.assertEqual(['foo', 'bar'], result)

    def test_process_result_value_null(self):
        dialect = None
        value = None
        result = self.sqltype.process_result_value(value, dialect)
        self.assertIsNone(result)
