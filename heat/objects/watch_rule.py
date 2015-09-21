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

"""WatchRule object."""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.db import api as db_api
from heat.objects import fields as heat_fields
from heat.objects import stack
from heat.objects import watch_data


class WatchRule(base.VersionedObject, base.VersionedObjectDictCompat):

    fields = {
        'id': fields.IntegerField(),
        'name': fields.StringField(nullable=True),
        'rule': heat_fields.JsonField(nullable=True),
        'state': fields.StringField(nullable=True),
        'last_evaluated': fields.DateTimeField(nullable=True),
        'stack_id': fields.StringField(),
        'stack': fields.ObjectField(stack.Stack),
        'watch_data': fields.ListOfObjectsField(watch_data.WatchData),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, rule, db_rule):
        for field in rule.fields:
            if field == 'stack':
                rule[field] = stack.Stack._from_db_object(
                    context, stack.Stack(), db_rule[field])
            elif field == 'watch_data':
                rule[field] = watch_data.WatchData.get_all_by_watch_rule_id(
                    context, db_rule['id'])
            else:
                rule[field] = db_rule[field]
        rule._context = context
        rule.obj_reset_changes()
        return rule

    @classmethod
    def get_by_id(cls, context, rule_id):
        db_rule = db_api.watch_rule_get(context, rule_id)
        return cls._from_db_object(context, cls(), db_rule)

    @classmethod
    def get_by_name(cls, context, watch_rule_name):
        db_rule = db_api.watch_rule_get_by_name(context, watch_rule_name)
        return cls._from_db_object(context, cls(), db_rule)

    @classmethod
    def get_all(cls, context):
        return [cls._from_db_object(context, cls(), db_rule)
                for db_rule in db_api.watch_rule_get_all(context)]

    @classmethod
    def get_all_by_stack(cls, context, stack_id):
        return [cls._from_db_object(context, cls(), db_rule)
                for db_rule in db_api.watch_rule_get_all_by_stack(context,
                                                                  stack_id)]

    @classmethod
    def update_by_id(cls, context, watch_id, values):
        db_api.watch_rule_update(context, watch_id, values)

    @classmethod
    def create(cls, context, values):
        return cls._from_db_object(context, cls(),
                                   db_api.watch_rule_create(context, values))

    @classmethod
    def delete(cls, context, watch_id):
        db_api.watch_rule_delete(context, watch_id)
