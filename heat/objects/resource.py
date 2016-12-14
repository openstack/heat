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


"""Resource object."""

import collections

from oslo_config import cfg
from oslo_versionedobjects import base
from oslo_versionedobjects import fields
import six
import tenacity

from heat.common import crypt
from heat.common import exception
from heat.common.i18n import _
from heat.db.sqlalchemy import api as db_api
from heat.objects import base as heat_base
from heat.objects import fields as heat_fields
from heat.objects import resource_data

cfg.CONF.import_opt('encrypt_parameters_and_properties', 'heat.common.config')


def retry_on_conflict(func):
    wrapper = tenacity.retry(
        stop=tenacity.stop_after_attempt(11),
        wait=tenacity.wait_random(max=0.002),
        retry=tenacity.retry_if_exception_type(
            exception.ConcurrentTransaction),
        reraise=True)
    return wrapper(func)


class ResourceCache(object):

    def __init__(self):
        self.delete_all()

    def delete_all(self):
        self.by_stack_id_name = collections.defaultdict(dict)

    def set_by_stack_id(self, resources):
        for res in six.itervalues(resources):
            self.by_stack_id_name[res.stack_id][res.name] = res


class Resource(
    heat_base.HeatObject,
    base.VersionedObjectDictCompat,
    base.ComparableVersionedObject,
):
    fields = {
        'id': fields.IntegerField(),
        'uuid': fields.StringField(),
        'stack_id': fields.StringField(),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'physical_resource_id': fields.StringField(nullable=True),
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
        'engine_id': fields.StringField(nullable=True),
        'atomic_key': fields.IntegerField(nullable=True),
        'current_template_id': fields.IntegerField(),
        'needed_by': heat_fields.ListField(nullable=True, default=None),
        'requires': heat_fields.ListField(nullable=True, default=None),
        'replaces': fields.IntegerField(nullable=True),
        'replaced_by': fields.IntegerField(nullable=True),
        'root_stack_id': fields.StringField(nullable=True),
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
            decrypted_data = crypt.decrypted_dict(resource.properties_data)
            resource.properties_data = decrypted_data

        resource._context = context
        resource.obj_reset_changes()
        return resource

    @classmethod
    def get_obj(cls, context, resource_id, refresh=False):
        resource_db = db_api.resource_get(context, resource_id,
                                          refresh=refresh)
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
        db_api.resource_delete(context, resource_id)

    @classmethod
    def exchange_stacks(cls, context, resource_id1, resource_id2):
        return db_api.resource_exchange_stacks(
            context,
            resource_id1,
            resource_id2)

    @classmethod
    def get_all_by_stack(cls, context, stack_id, filters=None):
        cache = context.cache(ResourceCache)
        resources = cache.by_stack_id_name.get(stack_id)
        if resources:
            return dict(resources)
        resources_db = db_api.resource_get_all_by_stack(context, stack_id,
                                                        filters)
        return cls._resources_to_dict(context, resources_db)

    @classmethod
    def _resources_to_dict(cls, context, resources_db):
        resources = [
            (
                resource_name,
                cls._from_db_object(cls(context), context, resource_db)
            )
            for resource_name, resource_db in six.iteritems(resources_db)
        ]
        return dict(resources)

    @classmethod
    def get_all_active_by_stack(cls, context, stack_id):
        resources_db = db_api.resource_get_all_active_by_stack(context,
                                                               stack_id)
        resources = [
            (
                resource_id,
                cls._from_db_object(cls(context), context, resource_db)
            )
            for resource_id, resource_db in six.iteritems(resources_db)
        ]
        return dict(resources)

    @classmethod
    def get_all_by_root_stack(cls, context, stack_id, filters, cache=False):
        resources_db = db_api.resource_get_all_by_root_stack(
            context,
            stack_id,
            filters)
        all = cls._resources_to_dict(context, resources_db)
        if cache:
            context.cache(ResourceCache).set_by_stack_id(all)
        return all

    @classmethod
    def purge_deleted(cls, context, stack_id):
        return db_api.resource_purge_deleted(context, stack_id)

    @classmethod
    def get_by_name_and_stack(cls, context, resource_name, stack_id):
        resource_db = db_api.resource_get_by_name_and_stack(
            context,
            resource_name,
            stack_id)
        return cls._from_db_object(cls(context), context, resource_db)

    @classmethod
    def get_all_by_physical_resource_id(cls, context, physical_resource_id):
        matches = db_api.resource_get_all_by_physical_resource_id(
            context,
            physical_resource_id)
        return [cls._from_db_object(cls(context), context, resource_db)
                for resource_db in matches]

    @classmethod
    def update_by_id(cls, context, resource_id, values):
        db_api.resource_update_and_save(context, resource_id, values)

    def update_and_save(self, values):
        db_api.resource_update_and_save(self._context, self.id, values)

    def select_and_update(self, values, expected_engine_id=None,
                          atomic_key=0):
        return db_api.resource_update(self._context, self.id, values,
                                      atomic_key=atomic_key,
                                      expected_engine_id=expected_engine_id)

    def refresh(self):
        resource_db = db_api.resource_get(self._context, self.id, refresh=True)
        return self.__class__._from_db_object(
            self,
            self._context,
            resource_db)

    @staticmethod
    def encrypt_properties_data(data):
        if cfg.CONF.encrypt_parameters_and_properties and data:
            result = crypt.encrypted_dict(data)
            return (True, result)
        return (False, data)

    def update_metadata(self, metadata):
        if self.rsrc_metadata != metadata:
            rows_updated = self.select_and_update(
                {'rsrc_metadata': metadata}, self.engine_id, self.atomic_key)
            if not rows_updated:
                action = _('metadata setting for resource %s') % self.name
                raise exception.ConcurrentTransaction(action=action)
