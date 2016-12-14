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


"""StackTag object."""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.db.sqlalchemy import api as db_api
from heat.objects import base as heat_base


class StackTag(
        heat_base.HeatObject,
        base.VersionedObjectDictCompat,
        base.ComparableVersionedObject,
):
    fields = {
        'id': fields.IntegerField(),
        'tag': fields.StringField(nullable=True),
        'stack_id': fields.StringField(),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, tag, db_tag):
        """Method to help with migration to objects.

        Converts a database entity to a formal object.
        """
        if db_tag is None:
            return None
        for field in tag.fields:
            tag[field] = db_tag[field]
        tag.obj_reset_changes()
        return tag

    @classmethod
    def get_obj(cls, context, tag):
        return cls._from_db_object(cls(context), tag)


class StackTagList(
        heat_base.HeatObject,
        base.ObjectListBase,
):

    fields = {
        'objects': fields.ListOfObjectsField('StackTag'),
    }

    def __init__(self, *args, **kwargs):
        self._changed_fields = set()
        super(StackTagList, self).__init__()

    @classmethod
    def get(cls, context, stack_id):
        db_tags = db_api.stack_tags_get(context, stack_id)
        if db_tags:
            return base.obj_make_list(context, cls(), StackTag, db_tags)

    @classmethod
    def set(cls, context, stack_id, tags):
        db_tags = db_api.stack_tags_set(context, stack_id, tags)
        if db_tags:
            return base.obj_make_list(context, cls(), StackTag, db_tags)

    @classmethod
    def delete(cls, context, stack_id):
        db_api.stack_tags_delete(context, stack_id)

    @classmethod
    def from_db_object(cls, context, db_tags):
        if db_tags is not None:
            return base.obj_make_list(context, cls(), StackTag, db_tags)
