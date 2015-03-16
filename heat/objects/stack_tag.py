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


"""
StackTag object
"""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields


class StackTag(base.VersionedObject,
               base.VersionedObjectDictCompat,
               base.ComparableVersionedObject):
    fields = {
        'id': fields.IntegerField(),
        'tag': fields.StringField(nullable=True),
        'stack_id': fields.StringField(),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
    }

    @staticmethod
    def _from_db_object(tag, db_tag):
        if db_tag is None:
            return None
        for field in tag.fields:
            tag[field] = db_tag[field]
        tag.obj_reset_changes()
        return tag

    @classmethod
    def get_obj(cls, context, tag):
        tag_obj = cls._from_db_object(cls(context), tag)
        return tag_obj
