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

from oslo_serialization import jsonutils
from sqlalchemy.dialects import mysql
from sqlalchemy.ext import mutable
from sqlalchemy import types


dumps = jsonutils.dumps
loads = jsonutils.loads


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
        if value is None:
            return None
        return loads(value)


class MutableList(mutable.Mutable, list):
    @classmethod
    def coerce(cls, key, value):
        if not isinstance(value, cls):
            if isinstance(value, list):
                return cls(value)
            return mutable.Mutable.coerce(key, value)
        else:
            return value

    def __delitem__(self, key):
        list.__delitem__(self, key)
        self.changed()

    def __setitem__(self, key, value):
        list.__setitem__(self, key, value)
        self.changed()

    def __getstate__(self):
        return list(self)

    def __setstate__(self, state):
        len = list.__len__(self)
        list.__delslice__(self, 0, len)
        list.__add__(self, state)
        self.changed()

    def append(self, value):
        list.append(self, value)
        self.changed()

    def remove(self, value):
        list.remove(self, value)
        self.changed()


class List(types.TypeDecorator):
    impl = types.Text

    def load_dialect_impl(self, dialect):
        if dialect.name == 'mysql':
            return dialect.type_descriptor(mysql.LONGTEXT())
        else:
            return self.impl

    def process_bind_param(self, value, dialect):
        return dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return loads(value)


MutableList.associate_with(List)
mutable.MutableDict.associate_with(LongText)
mutable.MutableDict.associate_with(Json)
