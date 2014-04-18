#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

'''
Interface for database access.

Usage:

    >>> from heat import db
    >>> db.event_get(context, event_id)
    # Event object received

The underlying driver is loaded . SQLAlchemy is currently the only
supported backend.
'''

from oslo.config import cfg

from heat.openstack.common.db import api as db_api

CONF = cfg.CONF
CONF.import_opt('backend', 'heat.openstack.common.db.options',
                group='database')


_BACKEND_MAPPING = {'sqlalchemy': 'heat.db.sqlalchemy.api'}

IMPL = db_api.DBAPI(CONF.database.backend, backend_mapping=_BACKEND_MAPPING,
                    lazy=True)


def get_engine():
    return IMPL.get_engine()


def get_session():
    return IMPL.get_session()


def raw_template_get(context, template_id):
    return IMPL.raw_template_get(context, template_id)


def raw_template_create(context, values):
    return IMPL.raw_template_create(context, values)


def resource_data_get_all(resource):
    return IMPL.resource_data_get_all(resource)


def resource_data_get(resource, key):
    return IMPL.resource_data_get(resource, key)


def resource_data_set(resource, key, value, redact=False):
    return IMPL.resource_data_set(resource, key, value, redact=redact)


def resource_data_get_by_key(context, resource_id, key):
    return IMPL.resource_data_get_by_key(context, resource_id, key)


def resource_data_delete(resource, key):
    """Remove a resource_data element associated to a resource."""
    return IMPL.resource_data_delete(resource, key)


def resource_get(context, resource_id):
    return IMPL.resource_get(context, resource_id)


def resource_get_all(context):
    return IMPL.resource_get_all(context)


def resource_create(context, values):
    return IMPL.resource_create(context, values)


def resource_exchange_stacks(context, resource_id1, resource_id2):
    return IMPL.resource_exchange_stacks(context, resource_id1, resource_id2)


def resource_get_all_by_stack(context, stack_id):
    return IMPL.resource_get_all_by_stack(context, stack_id)


def resource_get_by_name_and_stack(context, resource_name, stack_id):
    return IMPL.resource_get_by_name_and_stack(context,
                                               resource_name, stack_id)


def resource_get_by_physical_resource_id(context, physical_resource_id):
    return IMPL.resource_get_by_physical_resource_id(context,
                                                     physical_resource_id)


def stack_get(context, stack_id, show_deleted=False, tenant_safe=True):
    return IMPL.stack_get(context, stack_id, show_deleted=show_deleted,
                          tenant_safe=tenant_safe)


def stack_get_by_name_and_owner_id(context, stack_name, owner_id):
    return IMPL.stack_get_by_name_and_owner_id(context, stack_name,
                                               owner_id=owner_id)


def stack_get_by_name(context, stack_name):
    return IMPL.stack_get_by_name(context, stack_name)


def stack_get_all(context, limit=None, sort_keys=None, marker=None,
                  sort_dir=None, filters=None, tenant_safe=True,
                  show_deleted=False):
    return IMPL.stack_get_all(context, limit, sort_keys,
                              marker, sort_dir, filters, tenant_safe,
                              show_deleted)


def stack_get_all_by_owner_id(context, owner_id):
    return IMPL.stack_get_all_by_owner_id(context, owner_id)


def stack_count_all(context, filters=None, tenant_safe=True):
    return IMPL.stack_count_all(context, filters=filters,
                                tenant_safe=tenant_safe)


def stack_create(context, values):
    return IMPL.stack_create(context, values)


def stack_update(context, stack_id, values):
    return IMPL.stack_update(context, stack_id, values)


def stack_delete(context, stack_id):
    return IMPL.stack_delete(context, stack_id)


def stack_lock_create(stack_id, engine_id):
    return IMPL.stack_lock_create(stack_id, engine_id)


def stack_lock_steal(stack_id, old_engine_id, new_engine_id):
    return IMPL.stack_lock_steal(stack_id, old_engine_id, new_engine_id)


def stack_lock_release(stack_id, engine_id):
    return IMPL.stack_lock_release(stack_id, engine_id)


def user_creds_create(context):
    return IMPL.user_creds_create(context)


def user_creds_delete(context, user_creds_id):
    return IMPL.user_creds_delete(context, user_creds_id)


def user_creds_get(context_id):
    return IMPL.user_creds_get(context_id)


def event_get(context, event_id):
    return IMPL.event_get(context, event_id)


def event_get_all(context):
    return IMPL.event_get_all(context)


def event_get_all_by_tenant(context):
    return IMPL.event_get_all_by_tenant(context)


def event_get_all_by_stack(context, stack_id):
    return IMPL.event_get_all_by_stack(context, stack_id)


def event_count_all_by_stack(context, stack_id):
    return IMPL.event_count_all_by_stack(context, stack_id)


def event_create(context, values):
    return IMPL.event_create(context, values)


def watch_rule_get(context, watch_rule_id):
    return IMPL.watch_rule_get(context, watch_rule_id)


def watch_rule_get_by_name(context, watch_rule_name):
    return IMPL.watch_rule_get_by_name(context, watch_rule_name)


def watch_rule_get_all(context):
    return IMPL.watch_rule_get_all(context)


def watch_rule_get_all_by_stack(context, stack_id):
    return IMPL.watch_rule_get_all_by_stack(context, stack_id)


def watch_rule_create(context, values):
    return IMPL.watch_rule_create(context, values)


def watch_rule_update(context, watch_id, values):
    return IMPL.watch_rule_update(context, watch_id, values)


def watch_rule_delete(context, watch_id):
    return IMPL.watch_rule_delete(context, watch_id)


def watch_data_create(context, values):
    return IMPL.watch_data_create(context, values)


def watch_data_get_all(context):
    return IMPL.watch_data_get_all(context)


def software_config_create(context, values):
    return IMPL.software_config_create(context, values)


def software_config_get(context, config_id):
    return IMPL.software_config_get(context, config_id)


def software_config_delete(context, config_id):
    return IMPL.software_config_delete(context, config_id)


def software_deployment_create(context, values):
    return IMPL.software_deployment_create(context, values)


def software_deployment_get(context, deployment_id):
    return IMPL.software_deployment_get(context, deployment_id)


def software_deployment_get_all(context, server_id=None):
    return IMPL.software_deployment_get_all(context, server_id)


def software_deployment_update(context, deployment_id, values):
    return IMPL.software_deployment_update(context, deployment_id, values)


def software_deployment_delete(context, deployment_id):
    return IMPL.software_deployment_delete(context, deployment_id)


def db_sync(engine, version=None):
    """Migrate the database to `version` or the most recent version."""
    return IMPL.db_sync(engine, version=version)


def db_version(engine):
    """Display the current database version."""
    return IMPL.db_version(engine)
