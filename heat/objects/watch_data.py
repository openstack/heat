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

"""WatchData object."""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.db import api as db_api
from heat.objects import fields as heat_fields


class WatchData(base.VersionedObject, base.VersionedObjectDictCompat):

    fields = {
        'id': fields.IntegerField(),
        'data': heat_fields.JsonField(nullable=True),
        'watch_rule_id': fields.StringField(),
        'watch_rule': fields.ObjectField('WatchRule'),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, rule, db_data):
        from heat.objects import watch_rule
        for field in rule.fields:
            if field == 'watch_rule':
                rule[field] = watch_rule.WatchRule._from_db_object(
                    context,
                    watch_rule.WatchRule(),
                    db_data['watch_rule'])
            else:
                rule[field] = db_data[field]
        rule._context = context
        rule.obj_reset_changes()
        return rule

    @classmethod
    def create(cls, context, values):
        db_data = db_api.watch_data_create(context, values)
        return cls._from_db_object(context, cls(), db_data)

    @classmethod
    def get_all(cls, context):
        return [cls._from_db_object(context, cls(), db_data)
                for db_data in db_api.watch_data_get_all(context)]

    @classmethod
    def get_all_by_watch_rule_id(cls, context, watch_rule_id):
        return (cls._from_db_object(context, cls(), db_data)
                for db_data in db_api.watch_data_get_all_by_watch_rule_id(
                    context, watch_rule_id))
