# Copyright 2014 Intel Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


from oslo_serialization import jsonutils as json
from oslo_versionedobjects import fields
import six


class Json(fields.FieldType):
    def coerce(self, obj, attr, value):
        if isinstance(value, six.string_types):
            loaded = json.loads(value)
            return loaded
        return value

    def from_primitive(self, obj, attr, value):
        return self.coerce(obj, attr, value)

    def to_primitive(self, obj, attr, value):
        return json.dumps(value)


class JsonField(fields.AutoTypedField):
    AUTO_TYPE = Json()


class ListField(fields.AutoTypedField):
    AUTO_TYPE = fields.List(fields.FieldType())
