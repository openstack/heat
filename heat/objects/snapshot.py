# Copyright 2015 Intel Corp.
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


"""Snapshot object."""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.db.sqlalchemy import api as db_api
from heat.objects import base as heat_base
from heat.objects import fields as heat_fields


class Snapshot(
        heat_base.HeatObject,
        base.VersionedObjectDictCompat,
        base.ComparableVersionedObject,
):

    fields = {
        'id': fields.StringField(),
        'name': fields.StringField(nullable=True),
        'stack_id': fields.StringField(),
        'data': heat_fields.JsonField(nullable=True),
        'tenant': fields.StringField(),
        'status': fields.StringField(nullable=True),
        'status_reason': fields.StringField(nullable=True),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, snapshot, db_snapshot):
        for field in snapshot.fields:
            snapshot[field] = db_snapshot[field]
        snapshot._context = context
        snapshot.obj_reset_changes()
        return snapshot

    @classmethod
    def create(cls, context, values):
        return cls._from_db_object(
            context, cls(), db_api.snapshot_create(context, values))

    @classmethod
    def get_snapshot_by_stack(cls, context, snapshot_id, stack):
        return cls._from_db_object(
            context, cls(), db_api.snapshot_get_by_stack(
                context, snapshot_id, stack))

    @classmethod
    def update(cls, context, snapshot_id, values):
        db_snapshot = db_api.snapshot_update(context, snapshot_id, values)
        return cls._from_db_object(context, cls(), db_snapshot)

    @classmethod
    def delete(cls, context, snapshot_id):
        db_api.snapshot_delete(context, snapshot_id)

    @classmethod
    def get_all(cls, context, stack_id):
        return [cls._from_db_object(context, cls(), db_snapshot)
                for db_snapshot in db_api.snapshot_get_all(context, stack_id)]
