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


"""ResourceData object."""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.common import exception
from heat.db.sqlalchemy import api as db_api
from heat.objects import base as heat_base


class ResourceData(
    heat_base.HeatObject,
    base.VersionedObjectDictCompat,
    base.ComparableVersionedObject,
):
    fields = {
        'id': fields.IntegerField(),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'key': fields.StringField(nullable=True),
        'value': fields.StringField(nullable=True),
        'redact': fields.BooleanField(nullable=True),
        'resource_id': fields.IntegerField(),
        'decrypt_method': fields.StringField(nullable=True),
    }

    @staticmethod
    def _from_db_object(sdata, db_sdata):
        if db_sdata is None:
            return None
        for field in sdata.fields:
            sdata[field] = db_sdata[field]
        sdata.obj_reset_changes()
        return sdata

    @classmethod
    def get_all(cls, resource, *args, **kwargs):
        # this method only returns dict, so we won't use objects mechanism here
        return db_api.resource_data_get_all(resource.context,
                                            resource.id,
                                            *args,
                                            **kwargs)

    @classmethod
    def get_obj(cls, resource, key):
        raise exception.NotSupported(feature='ResourceData.get_obj')

    @classmethod
    def get_val(cls, resource, key):
        return db_api.resource_data_get(resource.context, resource.id, key)

    @classmethod
    def set(cls, resource, key, value, *args, **kwargs):
        db_data = db_api.resource_data_set(
            resource.context,
            resource.id,
            key,
            value,
            *args,
            **kwargs
        )
        return db_data

    @classmethod
    def get_by_key(cls, context, resource_id, key):
        db_rdata = db_api.resource_data_get_by_key(context, resource_id, key)
        return cls._from_db_object(cls(context), db_rdata)

    @classmethod
    def delete(cls, resource, key):
        db_api.resource_data_delete(resource.context, resource.id, key)
