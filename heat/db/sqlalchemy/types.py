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

from json import dumps
from json import loads
from sqlalchemy import types
from sqlalchemy.dialects import mysql


class LongText(types.TypeDecorator):
    impl = types.Text

    def load_dialect_impl(self, dialect):
        if dialect.name == 'mysql':
            return dialect.type_descriptor(mysql.LONGTEXT())
        else:
            return self.impl


class Json(LongText):

    def process_bind_param(self, value, dialect):
        return dumps(value)

    def process_result_value(self, value, dialect):
        return loads(value)


def associate_with(sqltype):
    # TODO(leizhang) When we removed sqlalchemy 0.7 dependence
    # we can import MutableDict directly and remove ./mutable.py
    try:
        from sqlalchemy.ext.mutable import MutableDict as sa_MutableDict
        sa_MutableDict.associate_with(Json)
    except ImportError:
        from heat.db.sqlalchemy.mutable import MutableDict
        MutableDict.associate_with(Json)

associate_with(LongText)
associate_with(Json)
