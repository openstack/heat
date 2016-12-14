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


"""UserCreds object."""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.db.sqlalchemy import api as db_api
from heat.objects import base as heat_base


@base.VersionedObjectRegistry.register
class UserCreds(
        heat_base.HeatObject,
        base.VersionedObjectDictCompat,
        base.ComparableVersionedObject,
):
    fields = {
        'id': fields.StringField(),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'username': fields.StringField(nullable=True),
        'password': fields.StringField(nullable=True),
        'tenant': fields.StringField(nullable=True),
        'tenant_id': fields.StringField(nullable=True),
        'trustor_user_id': fields.StringField(nullable=True),
        'trust_id': fields.StringField(nullable=True),
        'region_name': fields.StringField(nullable=True),
        'auth_url': fields.StringField(nullable=True),
        'decrypt_method': fields.StringField(nullable=True)
    }

    @staticmethod
    def _from_db_object(ucreds, db_ucreds, context=None):
        if db_ucreds is None:
            return db_ucreds
        ucreds._context = context
        for field in ucreds.fields:
            # TODO(Shao HE Feng), now the db layer delete the decrypt_method
            # field, just skip it here. and will add an encrypted_field later.
            if field == "decrypt_method":
                continue
            ucreds[field] = db_ucreds[field]
        ucreds.obj_reset_changes()
        return ucreds

    @classmethod
    def create(cls, context):
        user_creds_db = db_api.user_creds_create(context)
        return cls._from_db_object(cls(), user_creds_db)

    @classmethod
    def delete(cls, context, user_creds_id):
        db_api.user_creds_delete(context, user_creds_id)

    @classmethod
    def get_by_id(cls, context, user_creds_id):
        user_creds_db = db_api.user_creds_get(context, user_creds_id)
        user_creds = cls._from_db_object(cls(), user_creds_db)
        return user_creds
