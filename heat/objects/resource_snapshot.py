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


"""ResourceSnapshot object."""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.db import api as db_api
from heat.objects import base as heat_base
from heat.objects import fields as heat_fields


class ResourceSnapshot(
        heat_base.HeatObject,
        base.VersionedObjectDictCompat,
        base.ComparableVersionedObject,
):

    fields = {
        'id': fields.StringField(),
        'snapshot_id': fields.StringField(),
        'resource_name': fields.StringField(),
        'data': heat_fields.JsonField(nullable=True),
        'created_at': fields.DateTimeField(read_only=True),
    }

    @staticmethod
    def _from_db_object(context, resource_snapshot, db_resource_snapshot):
        for field in resource_snapshot.fields:
            resource_snapshot[field] = db_resource_snapshot[field]
        resource_snapshot._context = context
        resource_snapshot.obj_reset_changes()
        return resource_snapshot

    @classmethod
    def create(cls, context, values):
        return cls._from_db_object(
            context, cls(), db_api.resource_snapshot_create(context, values))

    @classmethod
    def get(cls, context, resource_snapshot_id):
        return cls._from_db_object(
            context, cls(), db_api.resource_snapshot_get(
                context, resource_snapshot_id))

    @classmethod
    def get_by_snapshot_and_rsrc(cls, context, snapshot_id, resource_name):
        return cls._from_db_object(
            context, cls(), db_api.resource_snapshot_get_by_snapshot_and_rsrc(
                context, snapshot_id, resource_name))

    @classmethod
    def update(cls, context, resource_snapshot_id, values):
        db_resource_snapshot = db_api.resource_snapshot_update(
            context, resource_snapshot_id, values)
        return cls._from_db_object(context, cls(), db_resource_snapshot)

    @classmethod
    def delete(cls, context, resource_snapshot_id):
        db_api.resource_snapshot_delete(context, resource_snapshot_id)

    @classmethod
    def delete_all_by_snapshot(cls, context, snapshot_id):
        rsrc_snaps = cls.get_all(context, snapshot_id)
        for rsrc_snap in rsrc_snaps:
            cls.delete(context, rsrc_snap.id)

    @classmethod
    def get_all(cls, context, snapshot_id):
        return [cls._from_db_object(context, cls(), db_resource_snapshot)
                for db_resource_snapshot in db_api.resource_snapshot_get_all(
                    context, snapshot_id)]
