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


"""SyncPoint object."""


from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.db.sqlalchemy import api as db_api
from heat.objects import base as heat_base
from heat.objects import fields as heat_fields


class SyncPoint(
        heat_base.HeatObject,
        base.VersionedObjectDictCompat,
        base.ComparableVersionedObject,
):

    fields = {
        'entity_id': fields.StringField(),
        'traversal_id': fields.StringField(),
        'is_update': fields.BooleanField(),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'atomic_key': fields.IntegerField(),
        'stack_id': fields.StringField(),
        'input_data': heat_fields.JsonField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, sdata, db_sdata):
        if db_sdata is None:
            return None
        for field in sdata.fields:
            sdata[field] = db_sdata[field]
        sdata._context = context
        sdata.obj_reset_changes()
        return sdata

    @classmethod
    def get_by_key(cls,
                   context,
                   entity_id,
                   traversal_id,
                   is_update):
        sync_point_db = db_api.sync_point_get(context,
                                              entity_id,
                                              traversal_id,
                                              is_update)
        return cls._from_db_object(context, cls(), sync_point_db)

    @classmethod
    def create(cls, context, values):
        sync_point_db = db_api.sync_point_create(context, values)
        return cls._from_db_object(context, cls(), sync_point_db)

    @classmethod
    def update_input_data(cls,
                          context,
                          entity_id,
                          traversal_id,
                          is_update,
                          atomic_key,
                          input_data):
        return db_api.sync_point_update_input_data(
            context,
            entity_id,
            traversal_id,
            is_update,
            atomic_key,
            input_data)

    @classmethod
    def delete_all_by_stack_and_traversal(cls,
                                          context,
                                          stack_id,
                                          traversal_id):
        return db_api.sync_point_delete_all_by_stack_and_traversal(
            context,
            stack_id,
            traversal_id)
