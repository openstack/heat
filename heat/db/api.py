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

"""Implementation of SQLAlchemy backend."""

import datetime
import functools
import itertools
import random

from oslo_config import cfg
from oslo_db import api as oslo_db_api
from oslo_db import exception as db_exception
from oslo_db import options
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import utils
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import timeutils
import sqlalchemy
from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import orm

from heat.common import crypt
from heat.common import exception
from heat.common.i18n import _
from heat.db import filters as db_filters
from heat.db import models
from heat.db import utils as db_utils
from heat.engine import environment as heat_environment
from heat.rpc import api as rpc_api

CONF = cfg.CONF
CONF.import_opt('hidden_stack_tags', 'heat.common.config')
CONF.import_opt('max_events_per_stack', 'heat.common.config')
CONF.import_group('profiler', 'heat.common.config')
CONF.import_opt('db_max_retries', 'oslo_db.options', group='database')
CONF.import_opt('db_retry_interval', 'oslo_db.options', group='database')
CONF.import_opt(
    'db_inc_retry_interval', 'oslo_db.options', group='database')
CONF.import_opt(
    'db_max_retry_interval', 'oslo_db.options', group='database')

options.set_defaults(CONF)

_facade = None

LOG = logging.getLogger(__name__)

# TODO(sbaker): fix tests so that sqlite_fk=True can be passed to configure
context_manager = enginefacade.transaction_context()


# utility methods


def get_engine():
    return context_manager.writer.get_engine()


def retry_on_db_error(func):
    @functools.wraps(func)
    def try_func(context, *args, **kwargs):
        wrapped = oslo_db_api.wrap_db_retry(
            max_retries=CONF.database.db_max_retries,
            retry_on_deadlock=True,
            retry_on_disconnect=True,
            retry_interval=CONF.database.db_retry_interval,
            inc_retry_interval=CONF.database.db_inc_retry_interval,
            max_retry_interval=CONF.database.db_max_retry_interval,
        )(func)
        return wrapped(context, *args, **kwargs)
    return try_func


def _soft_delete(context, obj):
    """Mark this object as deleted."""
    setattr(obj, 'deleted_at', timeutils.utcnow())


def _soft_delete_aware_query(context, *args, **kwargs):
    """Stack query helper that accounts for context's `show_deleted` field.

    :param show_deleted: if True, overrides context's show_deleted field.
    """

    query = context.session.query(*args)
    show_deleted = kwargs.get('show_deleted') or context.show_deleted

    if not show_deleted:
        query = query.filter_by(deleted_at=None)
    return query


# raw template


@context_manager.reader
def raw_template_get(context, template_id):
    return _raw_template_get(context, template_id)


def _raw_template_get(context, template_id):
    result = context.session.get(models.RawTemplate, template_id)

    if not result:
        raise exception.NotFound(_('raw template with id %s not found') %
                                 template_id)
    return result


@context_manager.writer
def raw_template_create(context, values):
    raw_template_ref = models.RawTemplate()
    raw_template_ref.update(values)
    raw_template_ref.save(context.session)
    return raw_template_ref


@context_manager.writer
def raw_template_update(context, template_id, values):
    raw_template_ref = _raw_template_get(context, template_id)
    # get only the changed values
    values = dict((k, v) for k, v in values.items()
                  if getattr(raw_template_ref, k) != v)

    if values:
        for k, v in values.items():
            setattr(raw_template_ref, k, v)

    return raw_template_ref


@context_manager.writer
def raw_template_delete(context, template_id):
    try:
        raw_template = _raw_template_get(context, template_id)
    except exception.NotFound:
        # Ignore not found
        return
    raw_tmpl_files_id = raw_template.files_id
    context.session.delete(raw_template)
    if raw_tmpl_files_id is None:
        return

    # If no other raw_template is referencing the same raw_template_files,
    # delete that too
    if context.session.query(models.RawTemplate).filter_by(
            files_id=raw_tmpl_files_id).first() is None:
        try:
            raw_tmpl_files = _raw_template_files_get(
                context, raw_tmpl_files_id)
        except exception.NotFound:
            # Ignore not found
            return
        context.session.delete(raw_tmpl_files)


# raw template files


@context_manager.writer
def raw_template_files_create(context, values):
    raw_templ_files_ref = models.RawTemplateFiles()
    raw_templ_files_ref.update(values)
    raw_templ_files_ref.save(context.session)
    return raw_templ_files_ref


@context_manager.reader
def raw_template_files_get(context, files_id):
    return _raw_template_files_get(context, files_id)


def _raw_template_files_get(context, files_id):
    result = context.session.get(models.RawTemplateFiles, files_id)
    if not result:
        raise exception.NotFound(
            _("raw_template_files with files_id %d not found") %
            files_id)
    return result


# resource


@context_manager.writer
def resource_create(context, values):
    return _resource_create(context, values)


def _resource_create(context, values):
    resource_ref = models.Resource()
    resource_ref.data = []
    resource_ref.attr_data = None
    resource_ref.rsrc_attr_data = None
    resource_ref.update(values)
    resource_ref.save(context.session)
    return resource_ref


@retry_on_db_error
@context_manager.writer
def resource_create_replacement(context,
                                existing_res_id,
                                new_res_values,
                                atomic_key, expected_engine_id=None):
    try:
        with context_manager.writer.independent.using(context):
            new_res = _resource_create(context, new_res_values)
            update_data = {'replaced_by': new_res.id}
            rows_updated = _resource_update(
                context, existing_res_id, update_data, atomic_key,
                expected_engine_id=expected_engine_id,
            )
        if not bool(rows_updated):
            data = {}
            if 'name' in new_res_values:
                data['resource_name'] = new_res_values['name']
            raise exception.UpdateInProgress(**data)
    except db_exception.DBReferenceError as exc:
        # New template_id no longer exists
        LOG.debug('Not creating replacement resource: %s', exc)
        return None
    else:
        return new_res


@context_manager.reader
def resource_get_all_by_stack(context, stack_id, filters=None):
    query = context.session.query(
        models.Resource
    ).filter_by(
        stack_id=stack_id
    ).options(
        orm.joinedload(models.Resource.attr_data),
        orm.joinedload(models.Resource.data),
        orm.joinedload(models.Resource.rsrc_prop_data),
    )

    query = db_filters.exact_filter(query, models.Resource, filters)
    results = query.all()

    return dict((res.name, res) for res in results)


@context_manager.reader
def resource_get_all_active_by_stack(context, stack_id):
    filters = {'stack_id': stack_id, 'action': 'DELETE', 'status': 'COMPLETE'}
    subquery = context.session.query(models.Resource.id).filter_by(**filters)

    results = context.session.query(models.Resource).filter_by(
        stack_id=stack_id).filter(
        models.Resource.id.notin_(subquery.scalar_subquery())
    ).options(
        orm.joinedload(models.Resource.attr_data),
        orm.joinedload(models.Resource.data),
        orm.joinedload(models.Resource.rsrc_prop_data),
    ).all()

    return dict((res.id, res) for res in results)


@context_manager.reader
def resource_get_all_by_root_stack(context, stack_id, filters=None,
                                   stack_id_only=False):
    query = context.session.query(
        models.Resource
    ).filter_by(
        root_stack_id=stack_id
    )

    if stack_id_only:
        query = query.options(
            orm.load_only(models.Resource.id, models.Resource.stack_id)
        )
    else:
        query = query.options(
            orm.joinedload(models.Resource.attr_data),
            orm.joinedload(models.Resource.data),
            orm.joinedload(models.Resource.rsrc_prop_data),
        )

    query = db_filters.exact_filter(query, models.Resource, filters)
    results = query.all()

    return dict((res.id, res) for res in results)


@context_manager.reader
def engine_get_all_locked_by_stack(context, stack_id):
    query = context.session.query(
        func.distinct(models.Resource.engine_id)
    ).filter(
        models.Resource.stack_id == stack_id,
        models.Resource.engine_id.isnot(None))
    return set(i[0] for i in query.all())


@context_manager.reader
def resource_get(context, resource_id, refresh=False, refresh_data=False):
    return _resource_get(context, resource_id, refresh=refresh,
                         refresh_data=refresh_data)


def _resource_get(context, resource_id, refresh=False, refresh_data=False):
    result = context.session.query(
        models.Resource
    ).filter_by(
        id=resource_id
    ).options(
        orm.joinedload(models.Resource.attr_data),
        orm.joinedload(models.Resource.data),
        orm.joinedload(models.Resource.rsrc_prop_data),
    ).first()
    if not result:
        raise exception.NotFound(_("resource with id %s not found") %
                                 resource_id)
    if refresh:
        context.session.refresh(result)
        if refresh_data:
            # ensure data is loaded (lazy or otherwise)
            result.data

    return result


@context_manager.reader
def resource_get_by_name_and_stack(context, resource_name, stack_id):
    result = context.session.query(
        models.Resource
    ).filter_by(
        name=resource_name
    ).filter_by(
        stack_id=stack_id
    ).options(
        orm.joinedload(models.Resource.attr_data),
        orm.joinedload(models.Resource.data),
        orm.joinedload(models.Resource.rsrc_prop_data),
    ).first()
    return result


@context_manager.reader
def resource_get_all_by_physical_resource_id(context, physical_resource_id):
    return list(
        _resource_get_all_by_physical_resource_id(
            context, physical_resource_id,
        )
    )


def _resource_get_all_by_physical_resource_id(context, physical_resource_id):
    results = context.session.query(
        models.Resource,
    ).filter_by(
        physical_resource_id=physical_resource_id,
    ).options(
        orm.joinedload(models.Resource.attr_data),
        orm.joinedload(models.Resource.data),
        orm.joinedload(models.Resource.rsrc_prop_data),
    ).all()

    for result in results:
        if context is None or context.is_admin or context.tenant_id in (
            result.stack.tenant, result.stack.stack_user_project_id,
        ):
            yield result


@context_manager.reader
def resource_get_by_physical_resource_id(context, physical_resource_id):
    results = _resource_get_all_by_physical_resource_id(
        context, physical_resource_id,
    )
    try:
        return next(results)
    except StopIteration:
        return None


@context_manager.reader
def resource_get_all(context):
    results = context.session.query(
        models.Resource,
    ).options(
        orm.joinedload(models.Resource.attr_data),
        orm.joinedload(models.Resource.data),
        orm.joinedload(models.Resource.rsrc_prop_data),
    ).all()

    if not results:
        raise exception.NotFound(_('no resources were found'))
    return results


@retry_on_db_error
@context_manager.writer
def resource_purge_deleted(context, stack_id):
    filters = {'stack_id': stack_id, 'action': 'DELETE', 'status': 'COMPLETE'}
    query = context.session.query(models.Resource)
    result = query.filter_by(**filters)
    attr_ids = [r.attr_data_id for r in result if r.attr_data_id is not None]
    result.delete()
    if attr_ids:
        context.session.query(models.ResourcePropertiesData).filter(
            models.ResourcePropertiesData.id.in_(attr_ids)).delete(
                synchronize_session=False)


def _add_atomic_key_to_values(values, atomic_key):
    if atomic_key is None:
        values['atomic_key'] = 1
    else:
        values['atomic_key'] = atomic_key + 1


@retry_on_db_error
@context_manager.writer
def resource_update(context, resource_id, values, atomic_key,
                    expected_engine_id=None):
    return _resource_update(
        context, resource_id, values, atomic_key,
        expected_engine_id=expected_engine_id,
    )


def _resource_update(
    context, resource_id, values, atomic_key, expected_engine_id=None,
):
    _add_atomic_key_to_values(values, atomic_key)
    rows_updated = context.session.query(models.Resource).filter_by(
        id=resource_id, engine_id=expected_engine_id,
        atomic_key=atomic_key).update(values)

    return bool(rows_updated)


@context_manager.writer
def resource_update_and_save(context, resource_id, values):
    resource = context.session.get(models.Resource, resource_id)
    resource.update(values)
    resource.save(context.session)
    return _resource_get(context, resource.id)


@context_manager.writer
def resource_delete(context, resource_id):
    resource = context.session.get(models.Resource, resource_id)
    if resource:
        context.session.delete(resource)
        if resource.attr_data_id is not None:
            attr_prop_data = context.session.get(
                models.ResourcePropertiesData, resource.attr_data_id)
            context.session.delete(attr_prop_data)


@context_manager.writer
def resource_exchange_stacks(context, resource_id1, resource_id2):
    res1 = context.session.get(models.Resource, resource_id1)
    res2 = context.session.get(models.Resource, resource_id2)

    res1.stack, res2.stack = res2.stack, res1.stack


@context_manager.writer
def resource_attr_id_set(context, resource_id, atomic_key, attr_id):
    values = {'attr_data_id': attr_id}
    _add_atomic_key_to_values(values, atomic_key)
    rows_updated = context.session.query(models.Resource).filter(and_(
        models.Resource.id == resource_id,
        models.Resource.atomic_key == atomic_key,
        models.Resource.engine_id.is_(None),
        or_(models.Resource.attr_data_id == attr_id,
            models.Resource.attr_data_id.is_(None)))).update(
                values)
    if rows_updated > 0:
        return True
    else:
        # Someone else set the attr_id first and/or we have a stale
        # view of the resource based on atomic_key, so delete the
        # resource_properties_data (attr) DB row.
        LOG.debug('Not updating res_id %(rid)s with attr_id %(aid)s',
                  {'rid': resource_id, 'aid': attr_id})
        context.session.query(
            models.ResourcePropertiesData).filter(
                models.ResourcePropertiesData.id == attr_id).delete()
        return False


@context_manager.writer
def resource_attr_data_delete(context, resource_id, attr_id):
    resource = context.session.get(models.Resource, resource_id)
    attr_prop_data = context.session.get(
        models.ResourcePropertiesData, attr_id)
    if resource:
        resource.update({'attr_data_id': None})
    if attr_prop_data:
        context.session.delete(attr_prop_data)


# resource data


@context_manager.reader
def resource_data_get_all(context, resource_id, data=None):
    """Looks up resource_data by resource.id.

    If data is encrypted, this method will decrypt the results.
    """
    if data is None:
        data = (context.session.query(models.ResourceData)
                .filter_by(resource_id=resource_id)).all()

    if not data:
        raise exception.NotFound(_('no resource data found'))

    ret = {}

    for res in data:
        if res.redact:
            try:
                ret[res.key] = crypt.decrypt(res.decrypt_method, res.value)
                continue
            except exception.InvalidEncryptionKey:
                LOG.exception('Failed to decrypt resource data %(rkey)s '
                              'for %(rid)s, ignoring.',
                              {'rkey': res.key, 'rid': resource_id})
        ret[res.key] = res.value
    return ret


@context_manager.reader
def resource_data_get(context, resource_id, key):
    """Lookup value of resource's data by key.

    Decrypts resource data if necessary.
    """
    result = _resource_data_get_by_key(context, resource_id, key)
    if result.redact:
        return crypt.decrypt(result.decrypt_method, result.value)
    return result.value


@context_manager.reader
def resource_data_get_by_key(context, resource_id, key):
    return _resource_data_get_by_key(context, resource_id, key)


def _resource_data_get_by_key(context, resource_id, key):
    """Looks up resource_data by resource_id and key.

    Does not decrypt resource_data.
    """
    result = (context.session.query(models.ResourceData)
              .filter_by(resource_id=resource_id)
              .filter_by(key=key).first())

    if not result:
        raise exception.NotFound(_('No resource data found'))
    return result


@context_manager.writer
def resource_data_set(context, resource_id, key, value, redact=False):
    """Save resource's key/value pair to database."""
    if redact:
        method, value = crypt.encrypt(value)
    else:
        method = ''
    try:
        current = _resource_data_get_by_key(context, resource_id, key)
    except exception.NotFound:
        current = models.ResourceData()
        current.key = key
        current.resource_id = resource_id
    current.redact = redact
    current.value = value
    current.decrypt_method = method
    current.save(session=context.session)
    return current


@context_manager.writer
def resource_data_delete(context, resource_id, key):
    result = _resource_data_get_by_key(context, resource_id, key)
    context.session.delete(result)


# resource properties data


@context_manager.writer
def resource_prop_data_create_or_update(context, values, rpd_id=None):
    return _resource_prop_data_create_or_update(context, values, rpd_id=rpd_id)


def _resource_prop_data_create_or_update(context, values, rpd_id=None):
    obj_ref = None
    if rpd_id is not None:
        obj_ref = context.session.query(
            models.ResourcePropertiesData).filter_by(id=rpd_id).first()
    if obj_ref is None:
        obj_ref = models.ResourcePropertiesData()
    obj_ref.update(values)
    obj_ref.save(context.session)
    return obj_ref


@context_manager.writer
def resource_prop_data_create(context, values):
    return _resource_prop_data_create_or_update(context, values)


@context_manager.reader
def resource_prop_data_get(context, resource_prop_data_id):
    result = context.session.get(
        models.ResourcePropertiesData, resource_prop_data_id)
    if result is None:
        raise exception.NotFound(
            _('ResourcePropertiesData with id %s not found') %
            resource_prop_data_id)
    return result


# stack


@context_manager.reader
def stack_get_by_name_and_owner_id(context, stack_name, owner_id):
    query = _soft_delete_aware_query(
        context, models.Stack
    ).options(
        orm.joinedload(models.Stack.raw_template),
    ).filter(
        sqlalchemy.or_(
            models.Stack.tenant == context.tenant_id,
            models.Stack.stack_user_project_id == context.tenant_id,
        )
    ).filter_by(name=stack_name).filter_by(owner_id=owner_id)
    return query.first()


@context_manager.reader
def stack_get_by_name(context, stack_name):
    return _stack_get_by_name(context, stack_name)


def _stack_get_by_name(context, stack_name):
    query = _soft_delete_aware_query(
        context, models.Stack
    ).options(
        orm.joinedload(models.Stack.raw_template),
    ).filter(
        sqlalchemy.or_(
            models.Stack.tenant == context.tenant_id,
            models.Stack.stack_user_project_id == context.tenant_id),
    ).filter_by(name=stack_name)
    return query.order_by(models.Stack.created_at).first()


@context_manager.reader
def stack_get(context, stack_id, show_deleted=False, eager_load=True):
    return _stack_get(
        context, stack_id, show_deleted=show_deleted, eager_load=eager_load
    )


def _stack_get(context, stack_id, show_deleted=False, eager_load=True):
    options = []
    if eager_load:
        options.append(orm.joinedload(models.Stack.raw_template))
    result = context.session.get(models.Stack, stack_id, options=options)

    deleted_ok = show_deleted or context.show_deleted
    if result is None or result.deleted_at is not None and not deleted_ok:
        return None

    # One exception to normal project scoping is users created by the
    # stacks in the stack_user_project_id (in the heat stack user domain)
    if (result is not None
        and context is not None and not context.is_admin
        and context.tenant_id not in (result.tenant,
                                      result.stack_user_project_id)):
        return None
    return result


@context_manager.reader
def stack_get_status(context, stack_id):
    query = context.session.query(models.Stack)
    query = query.options(
        orm.load_only(
            models.Stack.action,
            models.Stack.status,
            models.Stack.status_reason,
            models.Stack.updated_at,
        )
    )
    result = query.filter_by(id=stack_id).first()
    if result is None:
        raise exception.NotFound(_('Stack with id %s not found') % stack_id)

    return (result.action, result.status, result.status_reason,
            result.updated_at)


@context_manager.reader
def stack_get_all_by_owner_id(context, owner_id):
    return _stack_get_all_by_owner_id(context, owner_id)


def _stack_get_all_by_owner_id(context, owner_id):
    results = _soft_delete_aware_query(
        context, models.Stack,
    ).filter_by(
        owner_id=owner_id, backup=False,
    ).all()
    return results


@context_manager.reader
def stack_get_all_by_root_owner_id(context, owner_id):
    return list(_stack_get_all_by_root_owner_id(context, owner_id))


def _stack_get_all_by_root_owner_id(context, owner_id):
    for stack in _stack_get_all_by_owner_id(context, owner_id):
        yield stack
        for ch_st in _stack_get_all_by_root_owner_id(context, stack.id):
            yield ch_st


def _get_sort_keys(sort_keys, mapping):
    """Returns an array containing only allowed keys

    :param sort_keys: an array of strings
    :param mapping: a mapping from keys to DB column names
    :returns: filtered list of sort keys
    """
    if isinstance(sort_keys, str):
        sort_keys = [sort_keys]
    return [mapping[key] for key in sort_keys or [] if key in mapping]


def _paginate_query(context, query, model, limit=None, sort_keys=None,
                    marker=None, sort_dir=None):
    default_sort_keys = ['created_at']
    if not sort_keys:
        sort_keys = default_sort_keys
        if not sort_dir:
            sort_dir = 'desc'

    # This assures the order of the stacks will always be the same
    # even for sort_key values that are not unique in the database
    sort_keys = sort_keys + ['id']

    model_marker = None
    if marker:
        model_marker = context.session.get(model, marker)
    try:
        query = utils.paginate_query(query, model, limit, sort_keys,
                                     model_marker, sort_dir)
    except utils.InvalidSortKey as exc:
        err_msg = encodeutils.exception_to_unicode(exc)
        raise exception.Invalid(reason=err_msg)
    return query


def _query_stack_get_all(context, show_deleted=False,
                         show_nested=False, show_hidden=False, tags=None,
                         tags_any=None, not_tags=None, not_tags_any=None):
    if show_nested:
        query = _soft_delete_aware_query(
            context, models.Stack, show_deleted=show_deleted
        ).filter_by(backup=False)
    else:
        query = _soft_delete_aware_query(
            context, models.Stack, show_deleted=show_deleted
        ).filter_by(owner_id=None)

    if not context.is_admin:
        query = query.filter_by(tenant=context.tenant_id)

    query = query.options(orm.subqueryload(models.Stack.tags))
    if tags:
        for tag in tags:
            tag_alias = orm.aliased(models.StackTag)
            query = query.join(tag_alias, models.Stack.tags)
            query = query.filter(tag_alias.tag == tag)

    if tags_any:
        query = query.filter(
            models.Stack.tags.any(
                models.StackTag.tag.in_(tags_any)))

    if not_tags:
        subquery = _soft_delete_aware_query(
            context, models.Stack, show_deleted=show_deleted
        )
        for tag in not_tags:
            tag_alias = orm.aliased(models.StackTag)
            subquery = subquery.join(tag_alias, models.Stack.tags)
            subquery = subquery.filter(tag_alias.tag == tag)
        not_stack_ids = [s.id for s in subquery.all()]
        query = query.filter(models.Stack.id.notin_(not_stack_ids))

    if not_tags_any:
        query = query.filter(
            ~models.Stack.tags.any(
                models.StackTag.tag.in_(not_tags_any)))

    if not show_hidden and cfg.CONF.hidden_stack_tags:
        query = query.filter(
            ~models.Stack.tags.any(
                models.StackTag.tag.in_(cfg.CONF.hidden_stack_tags)))

    return query


@context_manager.reader
def stack_get_all(context, limit=None, sort_keys=None, marker=None,
                  sort_dir=None, filters=None,
                  show_deleted=False, show_nested=False, show_hidden=False,
                  tags=None, tags_any=None, not_tags=None,
                  not_tags_any=None, eager_load=False):
    query = _query_stack_get_all(context,
                                 show_deleted=show_deleted,
                                 show_nested=show_nested,
                                 show_hidden=show_hidden, tags=tags,
                                 tags_any=tags_any, not_tags=not_tags,
                                 not_tags_any=not_tags_any)
    if eager_load:
        query = query.options(orm.joinedload(models.Stack.raw_template))
    return _filter_and_page_query(context, query, limit, sort_keys,
                                  marker, sort_dir, filters).all()


def _filter_and_page_query(context, query, limit=None, sort_keys=None,
                           marker=None, sort_dir=None, filters=None):
    if filters is None:
        filters = {}

    sort_key_map = {rpc_api.STACK_NAME: models.Stack.name.key,
                    rpc_api.STACK_STATUS: models.Stack.status.key,
                    rpc_api.STACK_CREATION_TIME: models.Stack.created_at.key,
                    rpc_api.STACK_UPDATED_TIME: models.Stack.updated_at.key}
    valid_sort_keys = _get_sort_keys(sort_keys, sort_key_map)

    query = db_filters.exact_filter(query, models.Stack, filters)
    return _paginate_query(context, query, models.Stack, limit,
                           valid_sort_keys, marker, sort_dir)


@context_manager.reader
def stack_count_all(context, filters=None,
                    show_deleted=False, show_nested=False, show_hidden=False,
                    tags=None, tags_any=None, not_tags=None,
                    not_tags_any=None):
    query = _query_stack_get_all(context,
                                 show_deleted=show_deleted,
                                 show_nested=show_nested,
                                 show_hidden=show_hidden, tags=tags,
                                 tags_any=tags_any, not_tags=not_tags,
                                 not_tags_any=not_tags_any)
    query = db_filters.exact_filter(query, models.Stack, filters)
    return query.count()


@context_manager.writer
def stack_create(context, values):
    stack_ref = models.Stack()
    stack_ref.update(values)
    stack_name = stack_ref.name
    stack_ref.save(context.session)

    # Even though we just created a stack with this name, we may not find
    # it again because some unit tests create stacks with deleted_at set. Also
    # some backup stacks may not be found, for reasons that are unclear.
    earliest = _stack_get_by_name(context, stack_name)
    if earliest is not None and earliest.id != stack_ref.id:
        context.session.query(models.Stack).filter_by(
            id=stack_ref.id,
        ).delete()
        raise exception.StackExists(stack_name=stack_name)

    return stack_ref


@retry_on_db_error
@context_manager.writer
def stack_update(context, stack_id, values, exp_trvsl=None):
    query = (context.session.query(models.Stack)
             .filter(and_(models.Stack.id == stack_id),
                     (models.Stack.deleted_at.is_(None))))
    if not context.is_admin:
        query = query.filter(sqlalchemy.or_(
            models.Stack.tenant == context.tenant_id,
            models.Stack.stack_user_project_id == context.tenant_id))
    if exp_trvsl is not None:
        query = query.filter(models.Stack.current_traversal == exp_trvsl)
    rows_updated = query.update(values, synchronize_session=False)
    if not rows_updated:
        LOG.debug('Did not set stack state with values '
                  '%(vals)s, stack id: %(id)s with '
                  'expected traversal: %(trav)s',
                  {'id': stack_id, 'vals': str(values),
                   'trav': str(exp_trvsl)})
        if not _stack_get(context, stack_id, eager_load=False):
            raise exception.NotFound(
                _('Attempt to update a stack with id: '
                  '%(id)s %(msg)s') % {
                      'id': stack_id,
                      'msg': 'that does not exist'})
    return (rows_updated is not None and rows_updated > 0)


@context_manager.writer
def stack_delete(context, stack_id):
    s = _stack_get(context, stack_id, eager_load=False)
    if not s:
        raise exception.NotFound(_('Attempt to delete a stack with id: '
                                 '%(id)s %(msg)s') % {
                                     'id': stack_id,
                                     'msg': 'that does not exist'})
    attr_ids = []
    # normally the resources are deleted already by this point
    for r in s.resources:
        if r.attr_data_id is not None:
            attr_ids.append(r.attr_data_id)
        context.session.delete(r)
    if attr_ids:
        context.session.query(
            models.ResourcePropertiesData.id).filter(
                models.ResourcePropertiesData.id.in_(attr_ids)).delete(
                    synchronize_session=False)
    _soft_delete(context, s)


@context_manager.writer
def reset_stack_status(context, stack_id):
    return _reset_stack_status(context, stack_id)


# NOTE(stephenfin): This method uses separate transactions to delete nested
# stacks, thus it's the only private method that is allowed to open a
# transaction (via 'context.session.begin')
def _reset_stack_status(context, stack_id, stack=None):
    if stack is None:
        stack = context.session.get(models.Stack, stack_id)

    if stack is None:
        raise exception.NotFound(_('Stack with id %s not found') % stack_id)

    query = context.session.query(models.Resource).filter_by(
        status='IN_PROGRESS', stack_id=stack_id)
    query.update({'status': 'FAILED',
                  'status_reason': 'Stack status manually reset',
                  'engine_id': None})

    query = context.session.query(models.ResourceData)
    query = query.join(models.Resource)
    query = query.filter_by(stack_id=stack_id)
    query = query.filter(
        models.ResourceData.key.in_(heat_environment.HOOK_TYPES))
    data_ids = [data.id for data in query]

    if data_ids:
        query = context.session.query(models.ResourceData)
        query = query.filter(models.ResourceData.id.in_(data_ids))
        query.delete(synchronize_session='fetch')

    # commit what we've done already
    context.session.commit()

    query = context.session.query(models.Stack).filter_by(owner_id=stack_id)
    for child in query:
        _reset_stack_status(context, child.id, child)

    if stack.status == 'IN_PROGRESS':
        stack.status = 'FAILED'
        stack.status_reason = 'Stack status manually reset'

    context.session.query(
        models.StackLock
    ).filter_by(stack_id=stack_id).delete()


@context_manager.writer
def stack_tags_set(context, stack_id, tags):
    _stack_tags_delete(context, stack_id)
    result = []
    for tag in tags:
        stack_tag = models.StackTag()
        stack_tag.tag = tag
        stack_tag.stack_id = stack_id
        stack_tag.save(session=context.session)
        result.append(stack_tag)
    return result or None


@context_manager.writer
def stack_tags_delete(context, stack_id):
    return _stack_tags_delete(context, stack_id)


def _stack_tags_delete(context, stack_id):
    result = _stack_tags_get(context, stack_id)
    if result:
        for tag in result:
            context.session.delete(tag)


@context_manager.reader
def stack_tags_get(context, stack_id):
    return _stack_tags_get(context, stack_id)


def _stack_tags_get(context, stack_id):
    result = (context.session.query(models.StackTag)
              .filter_by(stack_id=stack_id)
              .all())
    return result or None


# stack lock


def _is_duplicate_error(exc):
    return isinstance(exc, db_exception.DBDuplicateEntry)


@oslo_db_api.wrap_db_retry(max_retries=3, retry_on_deadlock=True,
                           retry_on_disconnect=True,
                           retry_interval=0.5,
                           inc_retry_interval=True,
                           exception_checker=_is_duplicate_error)
def stack_lock_create(context, stack_id, engine_id):
    with context_manager.writer.independent.using(context) as session:
        lock = session.get(models.StackLock, stack_id)
        if lock is not None:
            return lock.engine_id
        session.add(models.StackLock(stack_id=stack_id, engine_id=engine_id))


def stack_lock_get_engine_id(context, stack_id):
    with context_manager.reader.independent.using(context) as session:
        lock = session.get(models.StackLock, stack_id)
        if lock is not None:
            return lock.engine_id


@context_manager.writer
def persist_state_and_release_lock(context, stack_id, engine_id, values):
    rows_updated = (context.session.query(models.Stack)
                    .filter(models.Stack.id == stack_id)
                    .update(values, synchronize_session=False))
    rows_affected = None
    if rows_updated is not None and rows_updated > 0:
        rows_affected = context.session.query(
            models.StackLock
        ).filter_by(stack_id=stack_id, engine_id=engine_id).delete()
    if not rows_affected:
        return True


def stack_lock_steal(context, stack_id, old_engine_id, new_engine_id):
    with context_manager.writer.independent.using(context) as session:
        lock = session.get(models.StackLock, stack_id)
        rows_affected = session.query(
            models.StackLock
        ).filter_by(stack_id=stack_id, engine_id=old_engine_id
                    ).update({"engine_id": new_engine_id})
    if not rows_affected:
        return lock.engine_id if lock is not None else True


def stack_lock_release(context, stack_id, engine_id):
    with context_manager.writer.independent.using(context) as session:
        rows_affected = session.query(
            models.StackLock
        ).filter_by(stack_id=stack_id, engine_id=engine_id).delete()
    if not rows_affected:
        return True


@context_manager.reader
def stack_get_root_id(context, stack_id):
    s = _stack_get(context, stack_id, eager_load=False)
    if not s:
        return None
    while s.owner_id:
        s = _stack_get(context, s.owner_id, eager_load=False)
    return s.id


@context_manager.reader
def stack_count_total_resources(context, stack_id):
    # count all resources which belong to the root stack
    return context.session.query(
        func.count(models.Resource.id)
    ).filter_by(root_stack_id=stack_id).scalar()


# user credentials


@context_manager.writer
def user_creds_create(context):
    values = context.to_dict()
    user_creds_ref = models.UserCreds()
    if values.get('trust_id'):
        method, trust_id = crypt.encrypt(values.get('trust_id'))
        user_creds_ref.trust_id = trust_id
        user_creds_ref.decrypt_method = method
        user_creds_ref.trustor_user_id = values.get('trustor_user_id')
        user_creds_ref.username = None
        user_creds_ref.password = None
        user_creds_ref.tenant = values.get('tenant')
        user_creds_ref.tenant_id = values.get('tenant_id')
        user_creds_ref.auth_url = values.get('auth_url')
        user_creds_ref.region_name = values.get('region_name')
    else:
        user_creds_ref.update(values)
        method, password = crypt.encrypt(values['password'])
        if len(str(password)) > 255:
            raise exception.Error(_("Length of OS_PASSWORD after encryption"
                                    " exceeds Heat limit (255 chars)"))
        user_creds_ref.password = password
        user_creds_ref.decrypt_method = method
    user_creds_ref.save(context.session)
    result = dict(user_creds_ref)

    if values.get('trust_id'):
        result['trust_id'] = values.get('trust_id')
    else:
        result['password'] = values.get('password')

    return result


@context_manager.reader
def user_creds_get(context, user_creds_id):
    db_result = context.session.get(models.UserCreds, user_creds_id)
    if db_result is None:
        return None
    # Return a dict copy of DB results, do not decrypt details into db_result
    # or it can be committed back to the DB in decrypted form
    result = dict(db_result)
    del result['decrypt_method']
    result['password'] = crypt.decrypt(
        db_result.decrypt_method, result['password'])
    result['trust_id'] = crypt.decrypt(
        db_result.decrypt_method, result['trust_id'])
    return result


@db_utils.retry_on_stale_data_error
@context_manager.writer
def user_creds_delete(context, user_creds_id):
    creds = context.session.get(models.UserCreds, user_creds_id)
    if not creds:
        raise exception.NotFound(
            _('Attempt to delete user creds with id '
              '%(id)s that does not exist') % {'id': user_creds_id})
    context.session.delete(creds)


# event


@context_manager.reader
def event_get_all_by_tenant(context, limit=None, marker=None,
                            sort_keys=None, sort_dir=None, filters=None):
    query = context.session.query(models.Event)
    query = db_filters.exact_filter(query, models.Event, filters)
    query = query.join(
        models.Event.stack
    ).filter_by(tenant=context.tenant_id).filter_by(deleted_at=None)
    filters = None
    return _events_filter_and_page_query(context, query, limit, marker,
                                         sort_keys, sort_dir, filters).all()


@context_manager.reader
def event_get_all_by_stack(context, stack_id, limit=None, marker=None,
                           sort_keys=None, sort_dir=None, filters=None):
    query = context.session.query(models.Event).filter_by(stack_id=stack_id)
    if filters and 'uuid' in filters:
        # retrieving a single event, so eager load its rsrc_prop_data detail
        query = query.options(orm.joinedload(models.Event.rsrc_prop_data))
    return _events_filter_and_page_query(context, query, limit, marker,
                                         sort_keys, sort_dir, filters).all()


def _events_paginate_query(context, query, model, limit=None, sort_keys=None,
                           marker=None, sort_dir=None):
    default_sort_keys = ['created_at']
    if not sort_keys:
        sort_keys = default_sort_keys
        if not sort_dir:
            sort_dir = 'desc'

    # This assures the order of the stacks will always be the same
    # even for sort_key values that are not unique in the database
    sort_keys = sort_keys + ['id']

    model_marker = None
    if marker:
        # not to use context.session.get(model, marker), because
        # user can only see the ID(column 'uuid') and the ID as the marker
        model_marker = context.session.query(
            model).filter_by(uuid=marker).first()
    try:
        query = utils.paginate_query(query, model, limit, sort_keys,
                                     model_marker, sort_dir)
    except utils.InvalidSortKey as exc:
        err_msg = encodeutils.exception_to_unicode(exc)
        raise exception.Invalid(reason=err_msg)

    return query


def _events_filter_and_page_query(context, query,
                                  limit=None, marker=None,
                                  sort_keys=None, sort_dir=None,
                                  filters=None):
    if filters is None:
        filters = {}

    sort_key_map = {rpc_api.EVENT_TIMESTAMP: models.Event.created_at.key,
                    rpc_api.EVENT_RES_TYPE: models.Event.resource_type.key}
    valid_sort_keys = _get_sort_keys(sort_keys, sort_key_map)

    query = db_filters.exact_filter(query, models.Event, filters)

    return _events_paginate_query(context, query, models.Event, limit,
                                  valid_sort_keys, marker, sort_dir)


@context_manager.reader
def event_count_all_by_stack(context, stack_id):
    return _event_count_all_by_stack(context, stack_id)


def _event_count_all_by_stack(context, stack_id):
    query = context.session.query(func.count(models.Event.id))
    return query.filter_by(stack_id=stack_id).scalar()


def _find_rpd_references(context, stack_id):
    ev_ref_ids = set(
        e.rsrc_prop_data_id for e
        in context.session.query(models.Event).filter_by(
            stack_id=stack_id,
        ).all()
    )
    rsrc_ref_ids = set(
        r.rsrc_prop_data_id for r
        in context.session.query(models.Resource).filter_by(
            stack_id=stack_id,
        ).all()
    )
    return ev_ref_ids | rsrc_ref_ids


def _all_backup_stack_ids(context, stack_id):
    """Iterate over all the IDs of all stacks related as stack/backup pairs.

    All backup stacks of a main stack, past and present (i.e. including those
    that are soft deleted), are included. The main stack itself is also
    included if the initial ID passed in is for a backup stack. The initial ID
    passed in is never included in the output.
    """
    stack = context.session.get(models.Stack, stack_id)
    if stack is None:
        LOG.error('Stack %s not found', stack_id)
        return
    is_backup = stack.name.endswith('*')

    if is_backup:
        main = context.session.get(models.Stack, stack.owner_id)
        if main is None:
            LOG.error('Main stack for backup "%s" %s not found',
                      stack.name, stack_id)
            return
        yield main.id
        for backup_id in _all_backup_stack_ids(context, main.id):
            if backup_id != stack_id:
                yield backup_id
    else:
        q_backup = context.session.query(models.Stack).filter(sqlalchemy.or_(
            models.Stack.tenant == context.tenant_id,
            models.Stack.stack_user_project_id == context.tenant_id))
        q_backup = q_backup.filter_by(name=stack.name + '*')
        q_backup = q_backup.filter_by(owner_id=stack_id)
        for backup in q_backup.all():
            yield backup.id


def _delete_event_rows(context, stack_id, limit):
    # MySQL does not support LIMIT in subqueries,
    # sqlite does not support JOIN in DELETE.
    # So we must manually supply the IN() values.
    # pgsql SHOULD work with the pure DELETE/JOIN below but that must be
    # confirmed via integration tests.
    query = context.session.query(models.Event).filter_by(
        stack_id=stack_id,
    )
    query = query.order_by(models.Event.id).limit(limit)
    id_pairs = [(e.id, e.rsrc_prop_data_id) for e in query.all()]
    if not id_pairs:
        return 0
    (ids, rsrc_prop_ids) = zip(*id_pairs)
    max_id = ids[-1]
    # delete the events
    retval = context.session.query(models.Event).filter(
        models.Event.id <= max_id).filter(
            models.Event.stack_id == stack_id).delete()

    # delete unreferenced resource_properties_data
    def del_rpd(rpd_ids):
        if not rpd_ids:
            return
        q_rpd = context.session.query(models.ResourcePropertiesData)
        q_rpd = q_rpd.filter(models.ResourcePropertiesData.id.in_(rpd_ids))
        q_rpd.delete(synchronize_session=False)

    if rsrc_prop_ids:
        clr_prop_ids = set(rsrc_prop_ids) - _find_rpd_references(context,
                                                                 stack_id)
        clr_prop_ids.discard(None)
        try:
            del_rpd(clr_prop_ids)
        except db_exception.DBReferenceError:
            LOG.debug('Checking backup/stack pairs for RPD references')
            found = False
            for partner_stack_id in _all_backup_stack_ids(context,
                                                          stack_id):
                found = True
                clr_prop_ids -= _find_rpd_references(context,
                                                     partner_stack_id)
            if not found:
                LOG.debug('No backup/stack pairs found for %s', stack_id)
                raise
            del_rpd(clr_prop_ids)

    return retval


@retry_on_db_error
@context_manager.writer
def event_create(context, values):
    if 'stack_id' in values and cfg.CONF.max_events_per_stack:
        # only count events and purge on average
        # 200.0/cfg.CONF.event_purge_batch_size percent of the time.
        check = (2.0 / cfg.CONF.event_purge_batch_size) > random.uniform(0, 1)
        if (
            check and _event_count_all_by_stack(
                context, values['stack_id']
            ) >= cfg.CONF.max_events_per_stack
        ):
            # prune
            try:
                _delete_event_rows(
                    context, values['stack_id'],
                    cfg.CONF.event_purge_batch_size,
                )
            except db_exception.DBError as exc:
                LOG.error('Failed to purge events: %s', str(exc))

    event_ref = models.Event()
    event_ref.update(values)
    event_ref.save(context.session)

    result = context.session.query(models.Event).filter_by(
        id=event_ref.id,
    ).options(
        orm.joinedload(models.Event.rsrc_prop_data)
    ).first()

    return result


# software config


@context_manager.writer
def software_config_create(context, values):
    obj_ref = models.SoftwareConfig()
    obj_ref.update(values)
    obj_ref.save(context.session)
    return obj_ref


@context_manager.reader
def software_config_get(context, config_id):
    return _software_config_get(context, config_id)


def _software_config_get(context, config_id):
    result = context.session.get(models.SoftwareConfig, config_id)
    if (result is not None and context is not None and not context.is_admin and
            result.tenant != context.tenant_id):
        result = None

    if not result:
        raise exception.NotFound(_('Software config with id %s not found') %
                                 config_id)
    return result


@context_manager.reader
def software_config_get_all(context, limit=None, marker=None):
    query = context.session.query(models.SoftwareConfig)
    if not context.is_admin:
        query = query.filter_by(tenant=context.tenant_id)
    return _paginate_query(context, query, models.SoftwareConfig,
                           limit=limit, marker=marker).all()


@context_manager.reader
def software_config_count_all(context):
    query = context.session.query(models.SoftwareConfig)
    if not context.is_admin:
        query = query.filter_by(tenant=context.tenant_id)
    return query.count()


@context_manager.writer
def software_config_delete(context, config_id):
    config = _software_config_get(context, config_id)
    # Query if the software config has been referenced by deployment.
    result = context.session.query(models.SoftwareDeployment).filter_by(
        config_id=config_id).first()
    if result:
        msg = (_("Software config with id %s can not be deleted as "
                 "it is referenced.") % config_id)
        raise exception.InvalidRestrictedAction(message=msg)
    context.session.delete(config)


# software deployment


@context_manager.writer
def software_deployment_create(context, values):
    obj_ref = models.SoftwareDeployment()
    obj_ref.update(values)

    try:
        obj_ref.save(context.session)
    except db_exception.DBReferenceError:
        # NOTE(tkajinam): config_id is the only FK in SoftwareDeployment
        err_msg = _('Config with id %s not found') % values['config_id']
        raise exception.Invalid(reason=err_msg)

    return _software_deployment_get(context, obj_ref.id)


@context_manager.reader
def software_deployment_get(context, deployment_id):
    return _software_deployment_get(context, deployment_id)


def _software_deployment_get(context, deployment_id):
    # TODO(stephenfin): Why doesn't options work with session.get?
    result = context.session.query(
        models.SoftwareDeployment,
    ).filter_by(
        id=deployment_id,
    ).options(
        orm.joinedload(models.SoftwareDeployment.config),
    ).first()
    if (result is not None and context is not None and not context.is_admin and
        context.tenant_id not in (result.tenant,
                                  result.stack_user_project_id)):
        result = None

    if not result:
        raise exception.NotFound(_('Deployment with id %s not found') %
                                 deployment_id)
    return result


@context_manager.reader
def software_deployment_get_all(context, server_id=None):
    sd = models.SoftwareDeployment
    query = context.session.query(sd).order_by(sd.created_at)
    if not context.is_admin:
        query = query.filter(
            sqlalchemy.or_(
                sd.tenant == context.tenant_id,
                sd.stack_user_project_id == context.tenant_id,
            )
        )
    if server_id:
        query = query.filter_by(server_id=server_id)

    query = query.join(
        models.SoftwareDeployment.config,
    ).options(
        orm.contains_eager(models.SoftwareDeployment.config)
    )

    return query.all()


@context_manager.reader
def software_deployment_count_all(context):
    sd = models.SoftwareDeployment
    query = context.session.query(sd)
    if not context.is_admin:
        query = query.filter(
            sqlalchemy.or_(
                sd.tenant == context.tenant_id,
                sd.stack_user_project_id == context.tenant_id,
            )
        )

    return query.count()


@context_manager.writer
def software_deployment_update(context, deployment_id, values):
    deployment = _software_deployment_get(context, deployment_id)
    try:
        for k, v in values.items():
            setattr(deployment, k, v)
    except db_exception.DBReferenceError:
        # NOTE(tkajinam): config_id is the only FK in SoftwareDeployment
        err_msg = _('Config with id %s not found') % values['config_id']
        raise exception.Invalid(reason=err_msg)
    return deployment


@context_manager.writer
def software_deployment_delete(context, deployment_id):
    deployment = _software_deployment_get(context, deployment_id)
    context.session.delete(deployment)


# snapshot


@context_manager.writer
def snapshot_create(context, values):
    obj_ref = models.Snapshot()
    obj_ref.update(values)
    obj_ref.save(context.session)
    return obj_ref


@context_manager.reader
def snapshot_get(context, snapshot_id):
    return _snapshot_get(context, snapshot_id)


def _snapshot_get(context, snapshot_id):
    result = context.session.get(models.Snapshot, snapshot_id)
    if (result is not None and context is not None and
            context.tenant_id != result.tenant):
        result = None

    if not result:
        raise exception.NotFound(_('Snapshot with id %s not found') %
                                 snapshot_id)
    return result


@context_manager.reader
def snapshot_get_by_stack(context, snapshot_id, stack):
    snapshot = _snapshot_get(context, snapshot_id)
    if snapshot.stack_id != stack.id:
        raise exception.SnapshotNotFound(snapshot=snapshot_id,
                                         stack=stack.name)

    return snapshot


@context_manager.writer
def snapshot_update(context, snapshot_id, values):
    snapshot = _snapshot_get(context, snapshot_id)
    snapshot.update(values)
    snapshot.save(context.session)
    return snapshot


@context_manager.writer
def snapshot_delete(context, snapshot_id):
    snapshot = _snapshot_get(context, snapshot_id)
    context.session.delete(snapshot)


@context_manager.reader
def snapshot_get_all_by_stack(context, stack_id):
    return context.session.query(models.Snapshot).filter_by(
        stack_id=stack_id, tenant=context.tenant_id)


@context_manager.reader
def snapshot_count_all_by_stack(context, stack_id):
    return context.session.query(models.Snapshot).filter_by(
        stack_id=stack_id, tenant=context.tenant_id).count()


# service


@context_manager.writer
def service_create(context, values):
    service = models.Service()
    service.update(values)
    service.save(context.session)
    return service


@context_manager.writer
def service_update(context, service_id, values):
    service = _service_get(context, service_id)
    values.update({'updated_at': timeutils.utcnow()})
    service.update(values)
    service.save(context.session)
    return service


@context_manager.writer
def service_delete(context, service_id, soft_delete=True):
    service = _service_get(context, service_id)
    if soft_delete:
        _soft_delete(context, service)
    else:
        context.session.delete(service)


@context_manager.reader
def service_get(context, service_id):
    return _service_get(context, service_id)


def _service_get(context, service_id):
    result = context.session.get(models.Service, service_id)
    if result is None:
        raise exception.EntityNotFound(entity='Service', name=service_id)
    return result


@context_manager.reader
def service_get_all(context):
    return context.session.query(models.Service).filter_by(
        deleted_at=None,
    ).all()


@context_manager.reader
def service_get_all_by_args(context, host, binary, hostname):
    return (context.session.query(models.Service).
            filter_by(host=host).
            filter_by(binary=binary).
            filter_by(hostname=hostname).all())


# purge


def purge_deleted(age, granularity='days', project_id=None, batch_size=20):
    def _validate_positive_integer(val, argname):
        try:
            val = int(val)
        except ValueError:
            raise exception.Error(_("%s should be an integer") % argname)

        if val < 0:
            raise exception.Error(_("%s should be a positive integer")
                                  % argname)
        return val

    age = _validate_positive_integer(age, 'age')
    batch_size = _validate_positive_integer(batch_size, 'batch_size')

    if granularity not in ('days', 'hours', 'minutes', 'seconds'):
        raise exception.Error(
            _("granularity should be days, hours, minutes, or seconds"))

    if granularity == 'days':
        age = age * 86400
    elif granularity == 'hours':
        age = age * 3600
    elif granularity == 'minutes':
        age = age * 60

    time_line = timeutils.utcnow() - datetime.timedelta(seconds=age)
    engine = get_engine()
    meta = sqlalchemy.MetaData()

    with engine.connect() as conn, conn.begin():
        stack = sqlalchemy.Table('stack', meta, autoload_with=conn)
        service = sqlalchemy.Table('service', meta, autoload_with=conn)

    # Purge deleted services
    srvc_del = service.delete().where(service.c.deleted_at < time_line)
    with engine.connect() as conn, conn.begin():
        conn.execute(srvc_del)

    # find the soft-deleted stacks that are past their expiry
    sel = sqlalchemy.select(
        stack.c.id,
        stack.c.raw_template_id,
        stack.c.prev_raw_template_id,
        stack.c.user_creds_id,
        stack.c.action,
        stack.c.status,
        stack.c.name)
    if project_id:
        stack_where = sel.where(and_(
            stack.c.tenant == project_id,
            stack.c.deleted_at < time_line))
    else:
        stack_where = sel.where(
            stack.c.deleted_at < time_line)

    with engine.connect() as conn, conn.begin():
        stacks = conn.execute(stack_where)

    while True:
        next_stacks_to_purge = list(itertools.islice(stacks, batch_size))
        if len(next_stacks_to_purge):
            _purge_stacks(next_stacks_to_purge, engine, meta)
        else:
            break


@oslo_db_api.wrap_db_retry(max_retries=3, retry_on_deadlock=True,
                           retry_interval=0.5, inc_retry_interval=True)
def _purge_stacks(stack_infos, engine, meta):
    """Purge some stacks and their releated events, raw_templates, etc.

    stack_infos is a list of lists of selected stack columns:
    [[id, raw_template_id, prev_raw_template_id, user_creds_id,
      action, status, name], ...]
    """

    with engine.connect() as conn, conn.begin():
        stack = sqlalchemy.Table('stack', meta, autoload_with=conn)
        stack_lock = sqlalchemy.Table('stack_lock', meta, autoload_with=conn)
        stack_tag = sqlalchemy.Table('stack_tag', meta, autoload_with=conn)
        resource = sqlalchemy.Table('resource', meta, autoload_with=conn)
        resource_data = sqlalchemy.Table(
            'resource_data', meta, autoload_with=conn)
        resource_properties_data = sqlalchemy.Table(
            'resource_properties_data', meta, autoload_with=conn)
        event = sqlalchemy.Table('event', meta, autoload_with=conn)
        raw_template = sqlalchemy.Table(
            'raw_template', meta, autoload_with=conn)
        raw_template_files = sqlalchemy.Table(
            'raw_template_files', meta, autoload_with=conn)
        user_creds = sqlalchemy.Table('user_creds', meta, autoload_with=conn)
        syncpoint = sqlalchemy.Table('sync_point', meta, autoload_with=conn)

    stack_info_str = ','.join([str(i) for i in stack_infos])
    LOG.info("Purging stacks %s", stack_info_str)

    # TODO(cwolfe): find a way to make this re-entrant with
    # reasonably sized transactions (good luck), or add
    # a cleanup for orphaned rows.
    stack_ids = [stack_info[0] for stack_info in stack_infos]

    # delete stack locks (just in case some got stuck)
    stack_lock_del = stack_lock.delete().where(
        stack_lock.c.stack_id.in_(stack_ids))
    with engine.connect() as conn, conn.begin():
        conn.execute(stack_lock_del)

    # delete stack tags
    stack_tag_del = stack_tag.delete().where(
        stack_tag.c.stack_id.in_(stack_ids))
    with engine.connect() as conn, conn.begin():
        conn.execute(stack_tag_del)

    # delete resource_data
    res_where = sqlalchemy.select(resource.c.id).where(
        resource.c.stack_id.in_(stack_ids))
    res_data_del = resource_data.delete().where(
        resource_data.c.resource_id.in_(res_where))
    with engine.connect() as conn, conn.begin():
        conn.execute(res_data_del)

    # clean up any sync_points that may have lingered
    sync_del = syncpoint.delete().where(
        syncpoint.c.stack_id.in_(stack_ids))
    with engine.connect() as conn, conn.begin():
        conn.execute(sync_del)

    # get rsrc_prop_data_ids to delete
    rsrc_prop_data_where = sqlalchemy.select(
        resource.c.rsrc_prop_data_id,
    ).where(
        resource.c.stack_id.in_(stack_ids))
    with engine.connect() as conn, conn.begin():
        rsrc_prop_data_ids = set(
            [i[0] for i in list(conn.execute(rsrc_prop_data_where))]
        )

    rsrc_prop_data_where = sqlalchemy.select(
        resource.c.attr_data_id,
    ).where(
        resource.c.stack_id.in_(stack_ids))
    with engine.connect() as conn, conn.begin():
        rsrc_prop_data_ids.update(
            [i[0] for i in list(conn.execute(rsrc_prop_data_where))]
        )

    rsrc_prop_data_where = sqlalchemy.select(
        event.c.rsrc_prop_data_id,
    ).where(
        event.c.stack_id.in_(stack_ids))
    with engine.connect() as conn, conn.begin():
        rsrc_prop_data_ids.update(
            [i[0] for i in list(conn.execute(rsrc_prop_data_where))]
        )

    # delete events
    event_del = event.delete().where(event.c.stack_id.in_(stack_ids))
    with engine.connect() as conn, conn.begin():
        conn.execute(event_del)

    # delete resources (normally there shouldn't be any)
    res_del = resource.delete().where(resource.c.stack_id.in_(stack_ids))
    with engine.connect() as conn, conn.begin():
        conn.execute(res_del)

    # delete resource_properties_data
    if rsrc_prop_data_ids:  # keep rpd's in events
        rsrc_prop_data_where = sqlalchemy.select(
            event.c.rsrc_prop_data_id,
        ).where(
            event.c.rsrc_prop_data_id.in_(rsrc_prop_data_ids))
        with engine.connect() as conn, conn.begin():
            ids = list(conn.execute(rsrc_prop_data_where))
        rsrc_prop_data_ids.difference_update([i[0] for i in ids])

    if rsrc_prop_data_ids:  # keep rpd's in resources
        rsrc_prop_data_where = sqlalchemy.select(
            resource.c.rsrc_prop_data_id,
        ).where(
            resource.c.rsrc_prop_data_id.in_(rsrc_prop_data_ids))
        with engine.connect() as conn, conn.begin():
            ids = list(conn.execute(rsrc_prop_data_where))
        rsrc_prop_data_ids.difference_update([i[0] for i in ids])

    if rsrc_prop_data_ids:  # delete if we have any
        rsrc_prop_data_del = resource_properties_data.delete().where(
            resource_properties_data.c.id.in_(rsrc_prop_data_ids))
        with engine.connect() as conn, conn.begin():
            conn.execute(rsrc_prop_data_del)

    # delete the stacks
    stack_del = stack.delete().where(stack.c.id.in_(stack_ids))
    with engine.connect() as conn, conn.begin():
        conn.execute(stack_del)

    # delete orphaned raw templates
    raw_template_ids = [i[1] for i in stack_infos if i[1] is not None]
    raw_template_ids.extend(i[2] for i in stack_infos if i[2] is not None)
    if raw_template_ids:  # keep those still referenced
        raw_tmpl_sel = sqlalchemy.select(stack.c.raw_template_id).where(
            stack.c.raw_template_id.in_(raw_template_ids))
        with engine.connect() as conn, conn.begin():
            raw_tmpl = [i[0] for i in conn.execute(raw_tmpl_sel)]
        raw_template_ids = set(raw_template_ids) - set(raw_tmpl)

    if raw_template_ids:  # keep those still referenced (previous tmpl)
        raw_tmpl_sel = sqlalchemy.select(
            stack.c.prev_raw_template_id,
        ).where(
            stack.c.prev_raw_template_id.in_(raw_template_ids))
        with engine.connect() as conn, conn.begin():
            raw_tmpl = [i[0] for i in conn.execute(raw_tmpl_sel)]
        raw_template_ids = raw_template_ids - set(raw_tmpl)

    if raw_template_ids:  # delete raw_templates if we have any
        raw_tmpl_file_sel = sqlalchemy.select(
            raw_template.c.files_id,
        ).where(
            raw_template.c.id.in_(raw_template_ids))
        with engine.connect() as conn, conn.begin():
            raw_tmpl_file_ids = [i[0] for i in conn.execute(
                raw_tmpl_file_sel)]

        raw_templ_del = raw_template.delete().where(
            raw_template.c.id.in_(raw_template_ids))
        with engine.connect() as conn, conn.begin():
            conn.execute(raw_templ_del)

        if raw_tmpl_file_ids:  # keep _files still referenced
            raw_tmpl_file_sel = sqlalchemy.select(
                raw_template.c.files_id,
            ).where(
                raw_template.c.files_id.in_(raw_tmpl_file_ids))
            with engine.connect() as conn, conn.begin():
                raw_tmpl_files = [i[0] for i in conn.execute(
                    raw_tmpl_file_sel)]
            raw_tmpl_file_ids = set(raw_tmpl_file_ids) \
                - set(raw_tmpl_files)

        if raw_tmpl_file_ids:  # delete _files if we have any
            raw_tmpl_file_del = raw_template_files.delete().where(
                raw_template_files.c.id.in_(raw_tmpl_file_ids))
            with engine.connect() as conn, conn.begin():
                conn.execute(raw_tmpl_file_del)

    # purge any user creds that are no longer referenced
    user_creds_ids = [i[3] for i in stack_infos if i[3] is not None]
    if user_creds_ids:  # keep those still referenced
        user_sel = sqlalchemy.select(stack.c.user_creds_id).where(
            stack.c.user_creds_id.in_(user_creds_ids))
        with engine.connect() as conn, conn.begin():
            users = [i[0] for i in conn.execute(user_sel)]
        user_creds_ids = set(user_creds_ids) - set(users)

    if user_creds_ids:  # delete if we have any
        usr_creds_del = user_creds.delete().where(
            user_creds.c.id.in_(user_creds_ids))
        with engine.connect() as conn, conn.begin():
            conn.execute(usr_creds_del)


# sync point


@context_manager.writer
def sync_point_delete_all_by_stack_and_traversal(context, stack_id,
                                                 traversal_id):
    rows_deleted = context.session.query(models.SyncPoint).filter_by(
        stack_id=stack_id, traversal_id=traversal_id).delete()
    return rows_deleted


@retry_on_db_error
@context_manager.writer
def sync_point_create(context, values):
    values['entity_id'] = str(values['entity_id'])
    sync_point_ref = models.SyncPoint()
    sync_point_ref.update(values)
    sync_point_ref.save(context.session)
    return sync_point_ref


@context_manager.reader
def sync_point_get(context, entity_id, traversal_id, is_update):
    entity_id = str(entity_id)
    return context.session.get(
        models.SyncPoint, (entity_id, traversal_id, is_update),
    )


@retry_on_db_error
@context_manager.writer
def sync_point_update_input_data(context, entity_id,
                                 traversal_id, is_update, atomic_key,
                                 input_data):
    entity_id = str(entity_id)
    rows_updated = context.session.query(models.SyncPoint).filter_by(
        entity_id=entity_id,
        traversal_id=traversal_id,
        is_update=is_update,
        atomic_key=atomic_key
    ).update({"input_data": input_data, "atomic_key": atomic_key + 1})
    return rows_updated
