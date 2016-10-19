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


"""SoftwareConfig object."""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.db.sqlalchemy import api as db_api
from heat.objects import base as heat_base
from heat.objects import fields as heat_fields


class SoftwareConfig(
        heat_base.HeatObject,
        base.VersionedObjectDictCompat,
        base.ComparableVersionedObject,
):
    fields = {
        'id': fields.StringField(),
        'name': fields.StringField(nullable=True),
        'group': fields.StringField(nullable=True),
        'tenant': fields.StringField(nullable=True),
        'config': heat_fields.JsonField(nullable=True),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, config, db_config):

        # SoftwareDeployment._from_db_object may attempt to load a None config
        if db_config is None:
            return None

        for field in config.fields:
            config[field] = db_config[field]
        config._context = context
        config.obj_reset_changes()
        return config

    @classmethod
    def create(cls, context, values):
        return cls._from_db_object(
            context, cls(), db_api.software_config_create(context, values))

    @classmethod
    def get_by_id(cls, context, config_id):
        return cls._from_db_object(
            context, cls(), db_api.software_config_get(context, config_id))

    @classmethod
    def get_all(cls, context, **kwargs):
        scs = db_api.software_config_get_all(context, **kwargs)
        return [cls._from_db_object(context, cls(), sc) for sc in scs]

    @classmethod
    def delete(cls, context, config_id):
        db_api.software_config_delete(context, config_id)
