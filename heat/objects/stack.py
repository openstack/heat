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


"""
Stack object
"""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields


from heat.common import exception
from heat.common.i18n import _
from heat.db import api as db_api
from heat.objects import fields as heat_fields
from heat.objects import raw_template
from heat.objects import stack_tag


class Stack(
    base.VersionedObject,
    base.VersionedObjectDictCompat,
    base.ComparableVersionedObject,
):
    fields = {
        'id': fields.StringField(),
        'name': fields.StringField(),
        'raw_template_id': fields.IntegerField(),
        'backup': fields.BooleanField(),
        'created_at': fields.DateTimeField(read_only=True),
        'deleted_at': fields.DateTimeField(nullable=True),
        'disable_rollback': fields.BooleanField(),
        'nested_depth': fields.IntegerField(),
        'owner_id': fields.StringField(nullable=True),
        'stack_user_project_id': fields.StringField(nullable=True),
        'tenant': fields.StringField(nullable=True),
        'timeout': fields.IntegerField(nullable=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'user_creds_id': fields.StringField(nullable=True),
        'username': fields.StringField(nullable=True),
        'action': fields.StringField(nullable=True),
        'status': fields.StringField(nullable=True),
        'status_reason': fields.StringField(nullable=True),
        'raw_template': fields.ObjectField('RawTemplate'),
        'convergence': fields.BooleanField(),
        'current_traversal': fields.StringField(),
        'current_deps': heat_fields.JsonField(),
        'prev_raw_template_id': fields.IntegerField(),
        'prev_raw_template': fields.ObjectField('RawTemplate'),
        'tag': fields.ObjectField('StackTag'),
        'parent_resource_name': fields.StringField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, stack, db_stack):
        for field in stack.fields:
            if field == 'raw_template':
                stack['raw_template'] = (
                    raw_template.RawTemplate.get_by_id(
                        context, db_stack['raw_template_id']))
            elif field == 'tag':
                if db_stack.get(field) is not None:
                    stack['tag'] = stack_tag.StackTag.get_obj(
                        db_stack.get(field)
                    )
                else:
                    stack['tag'] = None
            else:
                stack[field] = db_stack.__dict__.get(field)
        stack._context = context
        stack.obj_reset_changes()
        return stack

    @classmethod
    def get_root_id(cls, context, stack_id):
        return db_api.stack_get_root_id(context, stack_id)

    @classmethod
    def get_by_id(cls, context, stack_id, **kwargs):
        db_stack = db_api.stack_get(context, stack_id, **kwargs)
        if not db_stack:
            return db_stack
        stack = cls._from_db_object(context, cls(context), db_stack)
        return stack

    @classmethod
    def get_by_name_and_owner_id(cls, context, stack_name, owner_id):
        db_stack = db_api.stack_get_by_name_and_owner_id(
            context,
            stack_name,
            owner_id
        )
        if not db_stack:
            return db_stack
        stack = cls._from_db_object(context, cls(context), db_stack)
        return stack

    @classmethod
    def get_by_name(cls, context, stack_name):
        db_stack = db_api.stack_get_by_name(context, stack_name)
        if not db_stack:
            return db_stack
        stack = cls._from_db_object(context, cls(context), db_stack)
        return stack

    @classmethod
    def get_all(cls, context, *args, **kwargs):
        db_stacks = db_api.stack_get_all(context, *args, **kwargs)
        stacks = map(
            lambda db_stack: cls._from_db_object(
                context,
                cls(context),
                db_stack),
            db_stacks)
        return stacks

    @classmethod
    def get_all_by_owner_id(cls, context, owner_id):
        db_stacks = db_api.stack_get_all_by_owner_id(context, owner_id)
        stacks = map(
            lambda db_stack: cls._from_db_object(
                context,
                cls(context),
                db_stack),
            db_stacks)
        return stacks

    @classmethod
    def count_all(cls, context, **kwargs):
        return db_api.stack_count_all(context, **kwargs)

    @classmethod
    def count_total_resources(cls, context, stack_id):
        return db_api.stack_count_total_resources(context, stack_id)

    @classmethod
    def create(cls, context, values):
        return db_api.stack_create(context, values)

    @classmethod
    def update_by_id(cls, context, stack_id, values):
        return db_api.stack_update(context, stack_id, values)

    @classmethod
    def delete(cls, context, stack_id):
        return db_api.stack_delete(context, stack_id)

    def update_and_save(self, values):
        db_stack = self.__class__.update_by_id(self._context, self.id, values)
        self.refresh()
        return db_stack

    def __eq__(self, another):
        self.refresh()  # to make test object comparison work well
        return super(Stack, self).__eq__(another)

    def refresh(self):
        db_stack = db_api.stack_get(
            self._context, self.id, show_deleted=True)
        if db_stack is None:
            message = _('No stack exists with id "%s"') % str(self.id)
            raise exception.NotFound(message)
        db_stack.refresh()
        return self.__class__._from_db_object(
            self._context,
            self,
            db_stack
        )
