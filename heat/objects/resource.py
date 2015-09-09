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


from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_versionedobjects import base
from oslo_versionedobjects import fields
import six

from heat.common import crypt
from heat.db import api as db_api
from heat.objects import fields as heat_fields
from heat.objects import resource_data
from heat.objects import stack

cfg.CONF.import_opt('encrypt_parameters_and_properties', 'heat.common.config')


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
        'properties_data_encrypted': fields.BooleanField(default=False),
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
                resource['data'] = [resource_data.ResourceData._from_db_object(
                    resource_data.ResourceData(context), resd
                ) for resd in db_resource.data]
            else:
                resource[field] = db_resource[field]

        if resource.properties_data_encrypted and resource.properties_data:
            properties_data = {}
            for prop_name, prop_value in resource.properties_data.items():
                method, value = prop_value
                decrypted_value = crypt.decrypt(method, value)
                prop_string = jsonutils.loads(decrypted_value)
                properties_data[prop_name] = prop_string
            resource.properties_data = properties_data

        resource._context = context
        resource.obj_reset_changes()
        return resource

    @classmethod
    def get_obj(cls, context, resource_id):
        resource_db = db_api.resource_get(context, resource_id)
        return cls._from_db_object(cls(context), context, resource_db)

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
        return cls._from_db_object(cls(context), context,
                                   db_api.resource_create(context, values))

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
    def get_all_by_stack(cls, context, stack_id, key_id=False):
        resources_db = db_api.resource_get_all_by_stack(context,
                                                        stack_id, key_id)
        resources = [
            (
                resource_key,
                cls._from_db_object(cls(context), context, resource_db)
            )
            for resource_key, resource_db in six.iteritems(resources_db)
        ]
        return dict(resources)

    @classmethod
    def get_by_name_and_stack(cls, context, resource_name, stack_id):
        resource_db = db_api.resource_get_by_name_and_stack(
            context,
            resource_name,
            stack_id)
        return cls._from_db_object(cls(context), context, resource_db)

    @classmethod
    def get_by_physical_resource_id(cls, context, physical_resource_id):
        resource_db = db_api.resource_get_by_physical_resource_id(
            context,
            physical_resource_id)
        return cls._from_db_object(cls(context), context, resource_db)

    def update_and_save(self, values):
        resource_db = db_api.resource_get(self._context, self.id)
        resource_db.update_and_save(values)
        return self.refresh()

    def select_and_update(self, values, expected_engine_id=None,
                          atomic_key=0):
        return db_api.resource_update(self._context, self.id, values,
                                      atomic_key=atomic_key,
                                      expected_engine_id=expected_engine_id)

    def refresh(self, attrs=None):
        resource_db = db_api.resource_get(self._context, self.id)
        resource_db.refresh(attrs=attrs)
        return self.__class__._from_db_object(
            self,
            self._context,
            resource_db)

    @staticmethod
    def encrypt_properties_data(data):
        if cfg.CONF.encrypt_parameters_and_properties and data:
            result = {}
            for prop_name, prop_value in data.items():
                prop_string = jsonutils.dumps(prop_value)
                encrypted_value = crypt.encrypt(prop_string)
                result[prop_name] = encrypted_value
            return (True, result)
        return (False, data)
