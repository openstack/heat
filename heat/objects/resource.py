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
from oslo_log import log as logging
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
from heat.objects import resource_properties_data as rpd

cfg.CONF.import_opt('encrypt_parameters_and_properties', 'heat.common.config')

LOG = logging.getLogger(__name__)


def retry_on_conflict(func):
    wrapper = tenacity.retry(
        stop=tenacity.stop_after_attempt(11),
        wait=tenacity.wait_random(max=2),
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
        'attr_data': fields.ObjectField(
            rpd.ResourcePropertiesData, nullable=True),
        'attr_data_id': fields.IntegerField(nullable=True),
        'rsrc_metadata': heat_fields.JsonField(nullable=True),
        'data': fields.ListOfObjectsField(
            resource_data.ResourceData,
            nullable=True
        ),
        'rsrc_prop_data_id': fields.ObjectField(
            fields.IntegerField(nullable=True)),
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
    def _from_db_object(resource, context, db_resource, only_fields=None):
        if db_resource is None:
            return None
        for field in resource.fields:
            if (only_fields is not None and field not in only_fields
                    and field != 'id'):
                continue
            if field == 'data':
                resource['data'] = [resource_data.ResourceData._from_db_object(
                    resource_data.ResourceData(context), resd
                ) for resd in db_resource.data]
            elif field != 'attr_data':
                resource[field] = db_resource[field]

        if db_resource['rsrc_prop_data_id'] is not None:
            if hasattr(db_resource, '__dict__'):
                rpd_obj = db_resource.__dict__.get('rsrc_prop_data')
            else:
                rpd_obj = None
            if rpd_obj is not None:
                # Object is already eager loaded
                rpd_obj = (
                    rpd.ResourcePropertiesData._from_db_object(
                        rpd.ResourcePropertiesData(),
                        context,
                        rpd_obj))
                resource._properties_data = rpd_obj.data
            else:
                resource._properties_data = {}
            if db_resource['properties_data']:
                LOG.error(
                    'Unexpected condition where resource.rsrc_prop_data '
                    'and resource.properties_data are both not null. '
                    'rsrc_prop_data.id: %(rsrc_prop_data_id)s, '
                    'resource id: %(res_id)s',
                    {'rsrc_prop_data_id': resource['rsrc_prop_data'].id,
                     'res_id': resource['id']})
        elif db_resource['properties_data']:  # legacy field
            if db_resource['properties_data_encrypted']:
                decrypted_data = crypt.decrypted_dict(
                    db_resource['properties_data'])
                resource._properties_data = decrypted_data
            else:
                resource._properties_data = db_resource['properties_data']
        else:
            resource._properties_data = None

        if db_resource['attr_data'] is not None:
            resource._attr_data = rpd.ResourcePropertiesData._from_db_object(
                rpd.ResourcePropertiesData(context), context,
                db_resource['attr_data']).data
        else:
            resource._attr_data = None

        resource._context = context
        resource.obj_reset_changes()
        return resource

    @property
    def attr_data(self):
        return self._attr_data

    @property
    def properties_data(self):
        if (not self._properties_data and
                self.rsrc_prop_data_id is not None):
            LOG.info('rsrc_prop_data lazy load')
            rpd_obj = rpd.ResourcePropertiesData.get_by_id(
                self._context, self.rsrc_prop_data_id)
            self._properties_data = rpd_obj.data or {}
        return self._properties_data

    @classmethod
    def get_obj(cls, context, resource_id, refresh=False, fields=None):
        if fields is None or 'data' in fields:
            refresh_data = refresh
        else:
            refresh_data = False
        resource_db = db_api.resource_get(context, resource_id,
                                          refresh=refresh,
                                          refresh_data=refresh_data)
        return cls._from_db_object(cls(context), context, resource_db,
                                   only_fields=fields)

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
    def replacement(cls, context,
                    existing_res_id, existing_res_values,
                    new_res_values,
                    atomic_key=0, expected_engine_id=None):
        replacement = db_api.resource_create_replacement(context,
                                                         existing_res_id,
                                                         existing_res_values,
                                                         new_res_values,
                                                         atomic_key,
                                                         expected_engine_id)
        if replacement is None:
            return None
        return cls._from_db_object(cls(context), context, replacement)

    @classmethod
    def delete(cls, context, resource_id):
        db_api.resource_delete(context, resource_id)

    @classmethod
    def attr_data_delete(cls, context, resource_id, attr_id):
        db_api.resource_attr_data_delete(context, resource_id, attr_id)

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
    def get_all_stack_ids_by_root_stack(cls, context, stack_id):
        resources_db = db_api.resource_get_all_by_root_stack(
            context,
            stack_id,
            stack_id_only=True)
        return {db_res.stack_id for db_res in six.itervalues(resources_db)}

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

    @classmethod
    def select_and_update_by_id(cls, context, resource_id,
                                values, expected_engine_id=None,
                                atomic_key=0):
        return db_api.resource_update(context, resource_id, values,
                                      atomic_key=atomic_key,
                                      expected_engine_id=expected_engine_id)

    @classmethod
    def store_attributes(cls, context, resource_id, atomic_key,
                         attr_data, attr_id):
        attr_id = rpd.ResourcePropertiesData.create_or_update(
            context, attr_data, attr_id).id
        if db_api.resource_attr_id_set(
                context, resource_id, atomic_key, attr_id):
            return attr_id
        return None

    def refresh(self):
        resource_db = db_api.resource_get(self._context, self.id, refresh=True)
        return self.__class__._from_db_object(
            self,
            self._context,
            resource_db)

    def convert_to_convergence(self, current_template_id, requires):
        return self.update_and_save({
            'current_template_id': current_template_id,
            'requires': sorted(requires, reverse=True),
        })

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
            return True
        else:
            return False
