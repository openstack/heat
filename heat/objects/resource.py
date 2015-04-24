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
Resource object
"""


from oslo_versionedobjects import base
from oslo_versionedobjects import fields
import six

from heat.db import api as db_api
from heat.objects import fields as heat_fields
from heat.objects import resource_data
from heat.objects import stack


class Resource(
    base.VersionedObject,
    base.VersionedObjectDictCompat,
    base.ComparableVersionedObject,
):
    fields = {
        'id': fields.IntegerField(),
        'uuid': fields.StringField(),
        'stack_id': fields.StringField(),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'nova_instance': fields.StringField(nullable=True),
        'name': fields.StringField(nullable=True),
        'status': fields.StringField(nullable=True),
        'status_reason': fields.StringField(nullable=True),
        'action': fields.StringField(nullable=True),
        'rsrc_metadata': heat_fields.JsonField(nullable=True),
        'properties_data': heat_fields.JsonField(nullable=True),
        'data': fields.ListOfObjectsField(
            resource_data.ResourceData,
            nullable=True
        ),
        'stack': fields.ObjectField(stack.Stack),
        'engine_id': fields.StringField(nullable=True),
        'atomic_key': fields.IntegerField(nullable=True),
        'current_template_id': fields.IntegerField(),
        'needed_by': heat_fields.ListField(nullable=True, default=None),
        'requires': heat_fields.ListField(nullable=True, default=None),
        'replaces': fields.IntegerField(nullable=True),
        'replaced_by': fields.IntegerField(nullable=True),
    }

    @staticmethod
    def _from_db_object(resource, context, db_resource):
        if db_resource is None:
            return None
        for field in resource.fields:
            if field == 'data':
                resource['data'] = map(
                    lambda resd: resource_data.ResourceData._from_db_object(
                        resource_data.ResourceData(context), resd
                    ),
                    db_resource.data
                )
            else:
                resource[field] = db_resource[field]
        resource._context = context
        resource.obj_reset_changes()
        return resource

    @classmethod
    def get_obj(cls, context, resource_id):
        resource_db = db_api.resource_get(context, resource_id)
        resource = cls._from_db_object(cls(context), context, resource_db)
        return resource

    @classmethod
    def get_all(cls, context):
        resources_db = db_api.resource_get_all(context)
        resources = [
            (
                resource_name,
                cls._from_db_object(cls(context), context, resource_db)
            )
            for resource_name, resource_db in six.iteritems(resources_db)
        ]
        return dict(resources)

    @classmethod
    def create(cls, context, values):
        return db_api.resource_create(context, values)

    @classmethod
    def delete(cls, context, resource_id):
        resource_db = db_api.resource_get(context, resource_id)
        resource_db.delete()

    @classmethod
    def exchange_stacks(cls, context, resource_id1, resource_id2):
        return db_api.resource_exchange_stacks(
            context,
            resource_id1,
            resource_id2)

    @classmethod
    def get_all_by_stack(cls, context, stack_id):
        resources_db = db_api.resource_get_all_by_stack(context, stack_id)
        resources = [
            (
                resource_name,
                cls._from_db_object(cls(context), context, resource_db)
            )
            for resource_name, resource_db in six.iteritems(resources_db)
        ]
        return dict(resources)

    @classmethod
    def get_by_name_and_stack(cls, context, resource_name, stack_id):
        resource_db = db_api.resource_get_by_name_and_stack(
            context,
            resource_name,
            stack_id)
        resource = cls._from_db_object(cls(context), context, resource_db)
        return resource

    @classmethod
    def get_by_physical_resource_id(cls, context, physical_resource_id):
        resource_db = db_api.resource_get_by_physical_resource_id(
            context,
            physical_resource_id)
        resource = cls._from_db_object(cls(context), context, resource_db)
        return resource

    def update_and_save(self, values):
        resource_db = db_api.resource_get(self._context, self.id)
        resource_db.update_and_save(values)
        self._refresh()
        return resource_db

    def _refresh(self):
        return self.__class__._from_db_object(
            self,
            self._context,
            self.__class__.get_obj(self._context, self.id))

    def refresh(self, attrs=None):
        resource_db = db_api.resource_get(self._context, self.id)
        resource_db.refresh(attrs=attrs)
        return self._refresh()
