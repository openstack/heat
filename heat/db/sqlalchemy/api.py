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
import osprofiler.sqlalchemy
import six
import sqlalchemy
from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import orm
from sqlalchemy.orm import aliased as orm_aliased

from heat.common import crypt
from heat.common import exception
from heat.common.i18n import _
from heat.db.sqlalchemy import filters as db_filters
from heat.db.sqlalchemy import migration
from heat.db.sqlalchemy import models
from heat.db.sqlalchemy import utils as db_utils
from heat.engine import environment as heat_environment
from heat.rpc import api as rpc_api

CONF = cfg.CONF
CONF.import_opt('hidden_stack_tags', 'heat.common.config')
CONF.import_opt('max_events_per_stack', 'heat.common.config')
CONF.import_group('profiler', 'heat.common.config')

options.set_defaults(CONF)

_facade = None
db_context = enginefacade.transaction_context()

LOG = logging.getLogger(__name__)


# TODO(sbaker): fix tests so that sqlite_fk=True can be passed to configure
db_context.configure()


def get_facade():
    global _facade
    if _facade is None:

        # FIXME: get_facade() is called by the test suite startup,
        # but will not be called normally for API calls.
        # osprofiler / oslo_db / enginefacade currently don't have hooks
        # to talk to each other, however one needs to be added to oslo.db
        # to allow access to the Engine once constructed.
        db_context.configure(**CONF.database)
        _facade = db_context.get_legacy_facade()
        if CONF.profiler.enabled:
            if CONF.profiler.trace_sqlalchemy:
                osprofiler.sqlalchemy.add_tracing(sqlalchemy,
                                                  _facade.get_engine(),
                                                  "db")
    return _facade


def get_engine():
    return get_facade().get_engine()


def get_session():
    return get_facade().get_session()


def update_and_save(context, obj, values):
    with context.session.begin(subtransactions=True):
        for k, v in six.iteritems(values):
            setattr(obj, k, v)


def delete_softly(context, obj):
    """Mark this object as deleted."""
    update_and_save(context, obj, {'deleted_at': timeutils.utcnow()})


def soft_delete_aware_query(context, *args, **kwargs):
    """Stack query helper that accounts for context's `show_deleted` field.

    :param show_deleted: if True, overrides context's show_deleted field.
    """

    query = context.session.query(*args)
    show_deleted = kwargs.get('show_deleted') or context.show_deleted

    if not show_deleted:
        query = query.filter_by(deleted_at=None)
    return query


def raw_template_get(context, template_id):
    result = context.session.query(models.RawTemplate).get(template_id)

    if not result:
        raise exception.NotFound(_('raw template with id %s not found') %
                                 template_id)
    return result


def raw_template_create(context, values):
    raw_template_ref = models.RawTemplate()
    raw_template_ref.update(values)
    raw_template_ref.save(context.session)
    return raw_template_ref


def raw_template_update(context, template_id, values):
    raw_template_ref = raw_template_get(context, template_id)
    # get only the changed values
    values = dict((k, v) for k, v in values.items()
                  if getattr(raw_template_ref, k) != v)

    if values:
        update_and_save(context, raw_template_ref, values)

    return raw_template_ref


def raw_template_delete(context, template_id):
    raw_template = raw_template_get(context, template_id)
    raw_tmpl_files_id = raw_template.files_id
    session = context.session
    with session.begin(subtransactions=True):
        session.delete(raw_template)
        if raw_tmpl_files_id is None:
            return
        # If no other raw_template is referencing the same raw_template_files,
        # delete that too
        if session.query(models.RawTemplate).filter_by(
                files_id=raw_tmpl_files_id).first() is None:
            raw_tmpl_files = raw_template_files_get(context, raw_tmpl_files_id)
            session.delete(raw_tmpl_files)


def raw_template_files_create(context, values):
    session = context.session
    raw_templ_files_ref = models.RawTemplateFiles()
    raw_templ_files_ref.update(values)
    with session.begin():
        raw_templ_files_ref.save(session)
    return raw_templ_files_ref


def raw_template_files_get(context, files_id):
    result = context.session.query(models.RawTemplateFiles).get(files_id)
    if not result:
        raise exception.NotFound(
            _("raw_template_files with files_id %d not found") %
            files_id)
    return result


def resource_get(context, resource_id, refresh=False, refresh_data=False,
                 eager=True):
    query = context.session.query(models.Resource)
    query = query.options(orm.joinedload("data"))
    if eager:
        query = query.options(orm.joinedload("rsrc_prop_data"))

    result = query.get(resource_id)
    if not result:
        raise exception.NotFound(_("resource with id %s not found") %
                                 resource_id)
    if refresh:
        context.session.refresh(result)
        if refresh_data:
            # ensure data is loaded (lazy or otherwise)
            result.data

    return result


def resource_get_by_name_and_stack(context, resource_name, stack_id):
    result = context.session.query(
        models.Resource
    ).filter_by(
        name=resource_name
    ).filter_by(
        stack_id=stack_id
    ).options(orm.joinedload("data")).first()
    return result


def resource_get_all_by_physical_resource_id(context, physical_resource_id):
    results = (context.session.query(models.Resource)
               .filter_by(physical_resource_id=physical_resource_id)
               .all())

    for result in results:
        if context is None or context.is_admin or context.tenant_id in (
                result.stack.tenant, result.stack.stack_user_project_id):
            yield result


def resource_get_by_physical_resource_id(context, physical_resource_id):
    results = resource_get_all_by_physical_resource_id(context,
                                                       physical_resource_id)
    try:
        return next(results)
    except StopIteration:
        return None


def resource_get_all(context):
    results = context.session.query(models.Resource).all()

    if not results:
        raise exception.NotFound(_('no resources were found'))
    return results


@oslo_db_api.wrap_db_retry(max_retries=3, retry_on_deadlock=True,
                           retry_interval=0.5, inc_retry_interval=True)
def resource_purge_deleted(context, stack_id):
    filters = {'stack_id': stack_id, 'action': 'DELETE', 'status': 'COMPLETE'}
    query = context.session.query(models.Resource)
    result = query.filter_by(**filters)
    attr_ids = [r.attr_data_id for r in result if r.attr_data_id is not None]
    with context.session.begin(subtransactions=True):
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


@oslo_db_api.wrap_db_retry(max_retries=3, retry_on_deadlock=True,
                           retry_interval=0.5, inc_retry_interval=True)
def resource_update(context, resource_id, values, atomic_key,
                    expected_engine_id=None):
    session = context.session
    with session.begin(subtransactions=True):
        _add_atomic_key_to_values(values, atomic_key)
        rows_updated = session.query(models.Resource).filter_by(
            id=resource_id, engine_id=expected_engine_id,
            atomic_key=atomic_key).update(values)

        return bool(rows_updated)


def resource_update_and_save(context, resource_id, values):
    resource = context.session.query(models.Resource).get(resource_id)
    update_and_save(context, resource, values)


def resource_delete(context, resource_id):
    session = context.session
    with session.begin(subtransactions=True):
        resource = session.query(models.Resource).get(resource_id)
        if resource:
            session.delete(resource)
            if resource.attr_data_id is not None:
                attr_prop_data = session.query(
                    models.ResourcePropertiesData).get(resource.attr_data_id)
                session.delete(attr_prop_data)


def resource_attr_id_set(context, resource_id, atomic_key, attr_id):
    session = context.session
    with session.begin(subtransactions=True):
        values = {'attr_data_id': attr_id}
        _add_atomic_key_to_values(values, atomic_key)
        rows_updated = session.query(models.Resource).filter(and_(
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
            # resource_properties_data (attr) db row.
            LOG.debug('Not updating res_id %(rid)s with attr_id %(aid)s',
                      {'rid': resource_id, 'aid': attr_id})
            session.query(
                models.ResourcePropertiesData).filter(
                    models.ResourcePropertiesData.id == attr_id).delete()
            return False


def resource_attr_data_delete(context, resource_id, attr_id):
    session = context.session
    with session.begin(subtransactions=True):
        resource = session.query(models.Resource).get(resource_id)
        attr_prop_data = session.query(
            models.ResourcePropertiesData).get(attr_id)
        if resource:
            resource.update({'attr_data_id': None})
        if attr_prop_data:
            session.delete(attr_prop_data)


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
            ret[res.key] = crypt.decrypt(res.decrypt_method, res.value)
        else:
            ret[res.key] = res.value
    return ret


def resource_data_get(context, resource_id, key):
    """Lookup value of resource's data by key.

    Decrypts resource data if necessary.
    """
    result = resource_data_get_by_key(context,
                                      resource_id,
                                      key)
    if result.redact:
        return crypt.decrypt(result.decrypt_method, result.value)
    return result.value


def stack_tags_set(context, stack_id, tags):
    session = context.session
    with session.begin():
        stack_tags_delete(context, stack_id)
        result = []
        for tag in tags:
            stack_tag = models.StackTag()
            stack_tag.tag = tag
            stack_tag.stack_id = stack_id
            stack_tag.save(session=session)
            result.append(stack_tag)
        return result or None


def stack_tags_delete(context, stack_id):
    session = context.session
    with session.begin(subtransactions=True):
        result = stack_tags_get(context, stack_id)
        if result:
            for tag in result:
                session.delete(tag)


def stack_tags_get(context, stack_id):
    result = (context.session.query(models.StackTag)
              .filter_by(stack_id=stack_id)
              .all())
    return result or None


def resource_data_get_by_key(context, resource_id, key):
    """Looks up resource_data by resource_id and key.

    Does not decrypt resource_data.
    """
    result = (context.session.query(models.ResourceData)
              .filter_by(resource_id=resource_id)
              .filter_by(key=key).first())

    if not result:
        raise exception.NotFound(_('No resource data found'))
    return result


def resource_data_set(context, resource_id, key, value, redact=False):
    """Save resource's key/value pair to database."""
    if redact:
        method, value = crypt.encrypt(value)
    else:
        method = ''
    try:
        current = resource_data_get_by_key(context, resource_id, key)
    except exception.NotFound:
        current = models.ResourceData()
        current.key = key
        current.resource_id = resource_id
    current.redact = redact
    current.value = value
    current.decrypt_method = method
    current.save(session=context.session)
    return current


def resource_exchange_stacks(context, resource_id1, resource_id2):
    query = context.session.query(models.Resource)
    session = query.session

    with session.begin():
        res1 = query.get(resource_id1)
        res2 = query.get(resource_id2)

        res1.stack, res2.stack = res2.stack, res1.stack


def resource_data_delete(context, resource_id, key):
    result = resource_data_get_by_key(context, resource_id, key)
    session = context.session
    with session.begin(subtransactions=True):
        session.delete(result)


def resource_create(context, values):
    resource_ref = models.Resource()
    resource_ref.update(values)
    resource_ref.save(context.session)
    return resource_ref


def resource_create_replacement(context,
                                existing_res_id, existing_res_values,
                                new_res_values,
                                atomic_key, expected_engine_id=None):
    session = context.session
    try:
        with session.begin(subtransactions=True):
            new_res = resource_create(context, new_res_values)
            update_data = {'replaced_by': new_res.id}
            update_data.update(existing_res_values)
            if not resource_update(context,
                                   existing_res_id, update_data,
                                   atomic_key,
                                   expected_engine_id=expected_engine_id):
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


def resource_get_all_by_stack(context, stack_id, filters=None):
    query = context.session.query(
        models.Resource
    ).filter_by(
        stack_id=stack_id
    ).options(orm.joinedload("data")).options(orm.joinedload("rsrc_prop_data"))

    query = db_filters.exact_filter(query, models.Resource, filters)
    results = query.all()

    return dict((res.name, res) for res in results)


def resource_get_all_active_by_stack(context, stack_id):
    filters = {'stack_id': stack_id, 'action': 'DELETE', 'status': 'COMPLETE'}
    subquery = context.session.query(models.Resource.id).filter_by(**filters)

    results = context.session.query(models.Resource).filter_by(
        stack_id=stack_id).filter(
        models.Resource.id.notin_(subquery.as_scalar())
    ).options(orm.joinedload("data")).all()

    return dict((res.id, res) for res in results)


def resource_get_all_by_root_stack(context, stack_id, filters=None,
                                   stack_id_only=False):
    query = context.session.query(
        models.Resource
    ).filter_by(
        root_stack_id=stack_id
    )

    if stack_id_only:
        query = query.options(orm.load_only("id", "stack_id"))
    else:
        query = query.options(orm.joinedload("data")).options(
            orm.joinedload("rsrc_prop_data"))

    query = db_filters.exact_filter(query, models.Resource, filters)
    results = query.all()

    return dict((res.id, res) for res in results)


def engine_get_all_locked_by_stack(context, stack_id):
    query = context.session.query(
        func.distinct(models.Resource.engine_id)
    ).filter(
        models.Resource.stack_id == stack_id,
        models.Resource.engine_id.isnot(None))
    return set(i[0] for i in query.all())


def resource_prop_data_create_or_update(context, values, rpd_id=None):
    obj_ref = None
    if rpd_id is not None:
        obj_ref = context.session.query(
            models.ResourcePropertiesData).filter_by(id=rpd_id).first()
    if obj_ref is None:
        obj_ref = models.ResourcePropertiesData()
    obj_ref.update(values)
    obj_ref.save(context.session)
    return obj_ref


def resource_prop_data_create(context, values):
    return resource_prop_data_create_or_update(context, values)


def resource_prop_data_get(context, resource_prop_data_id):
    result = context.session.query(models.ResourcePropertiesData).get(
        resource_prop_data_id)
    if result is None:
        raise exception.NotFound(
            _('ResourcePropertiesData with id %s not found') %
            resource_prop_data_id)
    return result


def stack_get_by_name_and_owner_id(context, stack_name, owner_id):
    query = soft_delete_aware_query(
        context, models.Stack
    ).options(orm.joinedload("raw_template")).filter(sqlalchemy.or_(
        models.Stack.tenant == context.tenant_id,
        models.Stack.stack_user_project_id == context.tenant_id)
    ).filter_by(name=stack_name).filter_by(owner_id=owner_id)
    return query.first()


def stack_get_by_name(context, stack_name):
    query = soft_delete_aware_query(
        context, models.Stack
    ).filter(sqlalchemy.or_(
             models.Stack.tenant == context.tenant_id,
             models.Stack.stack_user_project_id == context.tenant_id)
             ).filter_by(name=stack_name)
    return query.first()


def stack_get(context, stack_id, show_deleted=False, eager_load=True):
    query = context.session.query(models.Stack)
    if eager_load:
        query = query.options(orm.joinedload("raw_template"))
    result = query.get(stack_id)

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


def stack_get_status(context, stack_id):
    query = context.session.query(models.Stack)
    query = query.options(
        orm.load_only("action", "status", "status_reason", "updated_at"))
    result = query.filter_by(id=stack_id).first()
    if result is None:
        raise exception.NotFound(_('Stack with id %s not found') % stack_id)

    return (result.action, result.status, result.status_reason,
            result.updated_at)


def stack_get_all_by_owner_id(context, owner_id):
    results = soft_delete_aware_query(
        context, models.Stack).filter_by(owner_id=owner_id,
                                         backup=False).all()
    return results


def stack_get_all_by_root_owner_id(context, owner_id):
    for stack in stack_get_all_by_owner_id(context, owner_id):
        yield stack
        for ch_st in stack_get_all_by_root_owner_id(context, stack.id):
            yield ch_st


def _get_sort_keys(sort_keys, mapping):
    """Returns an array containing only whitelisted keys

    :param sort_keys: an array of strings
    :param mapping: a mapping from keys to DB column names
    :returns: filtered list of sort keys
    """
    if isinstance(sort_keys, six.string_types):
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
        model_marker = context.session.query(model).get(marker)
    try:
        query = utils.paginate_query(query, model, limit, sort_keys,
                                     model_marker, sort_dir)
    except utils.InvalidSortKey as exc:
        err_msg = encodeutils.exception_to_unicode(exc)
        raise exception.Invalid(reason=err_msg)
    return query


def _query_stack_get_all(context,  show_deleted=False,
                         show_nested=False, show_hidden=False, tags=None,
                         tags_any=None, not_tags=None, not_tags_any=None):
    if show_nested:
        query = soft_delete_aware_query(
            context, models.Stack, show_deleted=show_deleted
        ).filter_by(backup=False)
    else:
        query = soft_delete_aware_query(
            context, models.Stack, show_deleted=show_deleted
        ).filter_by(owner_id=None)

    if not context.is_admin:
        query = query.filter_by(tenant=context.tenant_id)

    query = query.options(orm.subqueryload("tags"))
    if tags:
        for tag in tags:
            tag_alias = orm_aliased(models.StackTag)
            query = query.join(tag_alias, models.Stack.tags)
            query = query.filter(tag_alias.tag == tag)

    if tags_any:
        query = query.filter(
            models.Stack.tags.any(
                models.StackTag.tag.in_(tags_any)))

    if not_tags:
        subquery = soft_delete_aware_query(
            context, models.Stack, show_deleted=show_deleted
        )
        for tag in not_tags:
            tag_alias = orm_aliased(models.StackTag)
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
        query = query.options(orm.joinedload("raw_template"))
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
    whitelisted_sort_keys = _get_sort_keys(sort_keys, sort_key_map)

    query = db_filters.exact_filter(query, models.Stack, filters)
    return _paginate_query(context, query, models.Stack, limit,
                           whitelisted_sort_keys, marker, sort_dir)


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


def stack_create(context, values):
    stack_ref = models.Stack()
    stack_ref.update(values)
    stack_ref.save(context.session)
    return stack_ref


@oslo_db_api.wrap_db_retry(max_retries=3, retry_on_deadlock=True,
                           retry_interval=0.5, inc_retry_interval=True)
def stack_update(context, stack_id, values, exp_trvsl=None):
    session = context.session
    with session.begin(subtransactions=True):
        query = (session.query(models.Stack)
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
            if not stack_get(context, stack_id, eager_load=False):
                raise exception.NotFound(
                    _('Attempt to update a stack with id: '
                      '%(id)s %(msg)s') % {
                          'id': stack_id,
                          'msg': 'that does not exist'})
    session.expire_all()
    return (rows_updated is not None and rows_updated > 0)


def stack_delete(context, stack_id):
    s = stack_get(context, stack_id, eager_load=False)
    if not s:
        raise exception.NotFound(_('Attempt to delete a stack with id: '
                                 '%(id)s %(msg)s') % {
                                     'id': stack_id,
                                     'msg': 'that does not exist'})
    session = context.session
    with session.begin():
        attr_ids = []
        # normally the resources are deleted already by this point
        for r in s.resources:
            if r.attr_data_id is not None:
                attr_ids.append(r.attr_data_id)
            session.delete(r)
        if attr_ids:
            session.query(
                models.ResourcePropertiesData.id).filter(
                    models.ResourcePropertiesData.id.in_(attr_ids)).delete(
                        synchronize_session=False)
        delete_softly(context, s)


def _is_duplicate_error(exc):
    return isinstance(exc, db_exception.DBDuplicateEntry)


@oslo_db_api.wrap_db_retry(max_retries=3, retry_on_deadlock=True,
                           retry_interval=0.5, inc_retry_interval=True,
                           exception_checker=_is_duplicate_error)
def stack_lock_create(context, stack_id, engine_id):
    with db_context.writer.independent.using(context) as session:
        lock = session.query(models.StackLock).get(stack_id)
        if lock is not None:
            return lock.engine_id
        session.add(models.StackLock(stack_id=stack_id, engine_id=engine_id))


def stack_lock_get_engine_id(context, stack_id):
    with db_context.reader.independent.using(context) as session:
        lock = session.query(models.StackLock).get(stack_id)
        if lock is not None:
            return lock.engine_id


def persist_state_and_release_lock(context, stack_id, engine_id, values):
    session = context.session
    with session.begin():
        rows_updated = (session.query(models.Stack)
                        .filter(models.Stack.id == stack_id)
                        .update(values, synchronize_session=False))
        rows_affected = None
        if rows_updated is not None and rows_updated > 0:
            rows_affected = session.query(
                models.StackLock
            ).filter_by(stack_id=stack_id, engine_id=engine_id).delete()
    session.expire_all()
    if not rows_affected:
        return True


def stack_lock_steal(context, stack_id, old_engine_id, new_engine_id):
    with db_context.writer.independent.using(context) as session:
        lock = session.query(models.StackLock).get(stack_id)
        rows_affected = session.query(
            models.StackLock
        ).filter_by(stack_id=stack_id, engine_id=old_engine_id
                    ).update({"engine_id": new_engine_id})
    if not rows_affected:
        return lock.engine_id if lock is not None else True


def stack_lock_release(context, stack_id, engine_id):
    with db_context.writer.independent.using(context) as session:
        rows_affected = session.query(
            models.StackLock
        ).filter_by(stack_id=stack_id, engine_id=engine_id).delete()
    if not rows_affected:
        return True


def stack_get_root_id(context, stack_id):
    s = stack_get(context, stack_id, eager_load=False)
    if not s:
        return None
    while s.owner_id:
        s = stack_get(context, s.owner_id, eager_load=False)
    return s.id


def stack_count_total_resources(context, stack_id):
    # count all resources which belong to the root stack
    return context.session.query(
        func.count(models.Resource.id)
    ).filter_by(root_stack_id=stack_id).scalar()


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
        if len(six.text_type(password)) > 255:
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


def user_creds_get(context, user_creds_id):
    db_result = context.session.query(models.UserCreds).get(user_creds_id)
    if db_result is None:
        return None
    # Return a dict copy of db results, do not decrypt details into db_result
    # or it can be committed back to the DB in decrypted form
    result = dict(db_result)
    del result['decrypt_method']
    result['password'] = crypt.decrypt(
        db_result.decrypt_method, result['password'])
    result['trust_id'] = crypt.decrypt(
        db_result.decrypt_method, result['trust_id'])
    return result


@db_utils.retry_on_stale_data_error
def user_creds_delete(context, user_creds_id):
    creds = context.session.query(models.UserCreds).get(user_creds_id)
    if not creds:
        raise exception.NotFound(
            _('Attempt to delete user creds with id '
              '%(id)s that does not exist') % {'id': user_creds_id})
    with context.session.begin():
        context.session.delete(creds)


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


def _query_all_events_by_stack(context, stack_id):
    return context.session.query(models.Event).filter_by(stack_id=stack_id)


def event_get_all_by_stack(context, stack_id, limit=None, marker=None,
                           sort_keys=None, sort_dir=None, filters=None):
    query = _query_all_events_by_stack(context, stack_id)
    if filters and 'uuid' in filters:
        # retrieving a single event, so eager load its rsrc_prop_data detail
        query = query.options(orm.joinedload("rsrc_prop_data"))
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
        # not to use context.session.query(model).get(marker), because
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
    whitelisted_sort_keys = _get_sort_keys(sort_keys, sort_key_map)

    query = db_filters.exact_filter(query, models.Event, filters)

    return _events_paginate_query(context, query, models.Event, limit,
                                  whitelisted_sort_keys, marker, sort_dir)


def event_count_all_by_stack(context, stack_id):
    query = context.session.query(func.count(models.Event.id))
    return query.filter_by(stack_id=stack_id).scalar()


def _find_rpd_references(context, stack_id):
    ev_ref_ids = set(e.rsrc_prop_data_id for e
                     in _query_all_events_by_stack(context, stack_id).all())
    rsrc_ref_ids = set(r.rsrc_prop_data_id for r
                       in context.session.query(models.Resource).filter_by(
                           stack_id=stack_id).all())
    return ev_ref_ids | rsrc_ref_ids


def _all_backup_stack_ids(context, stack_id):
    """Iterate over all the IDs of all stacks related as stack/backup pairs.

    All backup stacks of a main stack, past and present (i.e. including those
    that are soft deleted), are included. The main stack itself is also
    included if the initial ID passed in is for a backup stack. The initial ID
    passed in is never included in the output.
    """
    query = context.session.query(models.Stack)
    stack = query.get(stack_id)
    if stack is None:
        LOG.error('Stack %s not found', stack_id)
        return
    is_backup = stack.name.endswith('*')

    if is_backup:
        main = query.get(stack.owner_id)
        if main is None:
            LOG.error('Main stack for backup "%s" %s not found',
                      stack.name, stack_id)
            return
        yield main.id
        for backup_id in _all_backup_stack_ids(context, main.id):
            if backup_id != stack_id:
                yield backup_id
    else:
        q_backup = query.filter(sqlalchemy.or_(
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
    session = context.session
    with session.begin():
        query = _query_all_events_by_stack(context, stack_id)
        query = query.order_by(models.Event.id).limit(limit)
        id_pairs = [(e.id, e.rsrc_prop_data_id) for e in query.all()]
        if not id_pairs:
            return 0
        (ids, rsrc_prop_ids) = zip(*id_pairs)
        max_id = ids[-1]
        # delete the events
        retval = session.query(models.Event.id).filter(
            models.Event.id <= max_id).filter(
                models.Event.stack_id == stack_id).delete()

        # delete unreferenced resource_properties_data
        def del_rpd(rpd_ids):
            if not rpd_ids:
                return
            q_rpd = session.query(models.ResourcePropertiesData)
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


def event_create(context, values):
    if 'stack_id' in values and cfg.CONF.max_events_per_stack:
        # only count events and purge on average
        # 200.0/cfg.CONF.event_purge_batch_size percent of the time.
        check = (2.0 / cfg.CONF.event_purge_batch_size) > random.uniform(0, 1)
        if (check and
            (event_count_all_by_stack(context, values['stack_id']) >=
             cfg.CONF.max_events_per_stack)):
            # prune
            try:
                _delete_event_rows(context, values['stack_id'],
                                   cfg.CONF.event_purge_batch_size)
            except db_exception.DBError as exc:
                LOG.error('Failed to purge events: %s', six.text_type(exc))
    event_ref = models.Event()
    event_ref.update(values)
    event_ref.save(context.session)
    return event_ref


def software_config_create(context, values):
    obj_ref = models.SoftwareConfig()
    obj_ref.update(values)
    obj_ref.save(context.session)
    return obj_ref


def software_config_get(context, config_id):
    result = context.session.query(models.SoftwareConfig).get(config_id)
    if (result is not None and context is not None and not context.is_admin and
            result.tenant != context.tenant_id):
        result = None

    if not result:
        raise exception.NotFound(_('Software config with id %s not found') %
                                 config_id)
    return result


def software_config_get_all(context, limit=None, marker=None):
    query = context.session.query(models.SoftwareConfig)
    if not context.is_admin:
        query = query.filter_by(tenant=context.tenant_id)
    return _paginate_query(context, query, models.SoftwareConfig,
                           limit=limit, marker=marker).all()


def software_config_delete(context, config_id):
    config = software_config_get(context, config_id)
    # Query if the software config has been referenced by deployment.
    result = context.session.query(models.SoftwareDeployment).filter_by(
        config_id=config_id).first()
    if result:
        msg = (_("Software config with id %s can not be deleted as "
                 "it is referenced.") % config_id)
        raise exception.InvalidRestrictedAction(message=msg)
    with context.session.begin():
        context.session.delete(config)


def software_deployment_create(context, values):
    obj_ref = models.SoftwareDeployment()
    obj_ref.update(values)
    session = context.session

    with session.begin():
        obj_ref.save(session)

    return obj_ref


def software_deployment_get(context, deployment_id):
    result = context.session.query(
        models.SoftwareDeployment).get(deployment_id)
    if (result is not None and context is not None and not context.is_admin and
        context.tenant_id not in (result.tenant,
                                  result.stack_user_project_id)):
        result = None

    if not result:
        raise exception.NotFound(_('Deployment with id %s not found') %
                                 deployment_id)
    return result


def software_deployment_get_all(context, server_id=None):
    sd = models.SoftwareDeployment
    query = context.session.query(sd).order_by(sd.created_at)
    if not context.is_admin:
        query = query.filter(sqlalchemy.or_(
            sd.tenant == context.tenant_id,
            sd.stack_user_project_id == context.tenant_id))
    if server_id:
        query = query.filter_by(server_id=server_id)

    return query.all()


def software_deployment_update(context, deployment_id, values):
    deployment = software_deployment_get(context, deployment_id)
    update_and_save(context, deployment, values)
    return deployment


def software_deployment_delete(context, deployment_id):
    deployment = software_deployment_get(context, deployment_id)
    session = context.session
    with session.begin(subtransactions=True):
        session.delete(deployment)


def snapshot_create(context, values):
    obj_ref = models.Snapshot()
    obj_ref.update(values)
    obj_ref.save(context.session)
    return obj_ref


def snapshot_get(context, snapshot_id):
    result = context.session.query(models.Snapshot).get(snapshot_id)
    if (result is not None and context is not None and
            context.tenant_id != result.tenant):
        result = None

    if not result:
        raise exception.NotFound(_('Snapshot with id %s not found') %
                                 snapshot_id)
    return result


def snapshot_get_by_stack(context, snapshot_id, stack):
    snapshot = snapshot_get(context, snapshot_id)
    if snapshot.stack_id != stack.id:
        raise exception.SnapshotNotFound(snapshot=snapshot_id,
                                         stack=stack.name)

    return snapshot


def snapshot_update(context, snapshot_id, values):
    snapshot = snapshot_get(context, snapshot_id)
    snapshot.update(values)
    snapshot.save(context.session)
    return snapshot


def snapshot_delete(context, snapshot_id):
    snapshot = snapshot_get(context, snapshot_id)
    with context.session.begin():
        context.session.delete(snapshot)


def snapshot_get_all(context, stack_id):
    return context.session.query(models.Snapshot).filter_by(
        stack_id=stack_id, tenant=context.tenant_id)


def service_create(context, values):
    service = models.Service()
    service.update(values)
    service.save(context.session)
    return service


def service_update(context, service_id, values):
    service = service_get(context, service_id)
    values.update({'updated_at': timeutils.utcnow()})
    service.update(values)
    service.save(context.session)
    return service


def service_delete(context, service_id, soft_delete=True):
    service = service_get(context, service_id)
    session = context.session
    with session.begin():
        if soft_delete:
            delete_softly(context, service)
        else:
            session.delete(service)


def service_get(context, service_id):
    result = context.session.query(models.Service).get(service_id)
    if result is None:
        raise exception.EntityNotFound(entity='Service', name=service_id)
    return result


def service_get_all(context):
    return (context.session.query(models.Service).
            filter_by(deleted_at=None).all())


def service_get_all_by_args(context, host, binary, hostname):
    return (context.session.query(models.Service).
            filter_by(host=host).
            filter_by(binary=binary).
            filter_by(hostname=hostname).all())


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
    meta.bind = engine

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    service = sqlalchemy.Table('service', meta, autoload=True)

    # Purge deleted services
    srvc_del = service.delete().where(service.c.deleted_at < time_line)
    engine.execute(srvc_del)

    # find the soft-deleted stacks that are past their expiry
    sel = sqlalchemy.select([stack.c.id, stack.c.raw_template_id,
                             stack.c.prev_raw_template_id,
                             stack.c.user_creds_id,
                             stack.c.action,
                             stack.c.status,
                             stack.c.name])
    if project_id:
        stack_where = sel.where(and_(
            stack.c.tenant == project_id,
            stack.c.deleted_at < time_line))
    else:
        stack_where = sel.where(
            stack.c.deleted_at < time_line)

    stacks = engine.execute(stack_where)

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

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    stack_lock = sqlalchemy.Table('stack_lock', meta, autoload=True)
    stack_tag = sqlalchemy.Table('stack_tag', meta, autoload=True)
    resource = sqlalchemy.Table('resource', meta, autoload=True)
    resource_data = sqlalchemy.Table('resource_data', meta, autoload=True)
    resource_properties_data = sqlalchemy.Table(
        'resource_properties_data', meta, autoload=True)
    event = sqlalchemy.Table('event', meta, autoload=True)
    raw_template = sqlalchemy.Table('raw_template', meta, autoload=True)
    raw_template_files = sqlalchemy.Table('raw_template_files', meta,
                                          autoload=True)
    user_creds = sqlalchemy.Table('user_creds', meta, autoload=True)
    syncpoint = sqlalchemy.Table('sync_point', meta, autoload=True)

    stack_info_str = ','.join([str(i) for i in stack_infos])
    LOG.info("Purging stacks %s", stack_info_str)

    # TODO(cwolfe): find a way to make this re-entrant with
    # reasonably sized transactions (good luck), or add
    # a cleanup for orphaned rows.
    stack_ids = [stack_info[0] for stack_info in stack_infos]
    # delete stack locks (just in case some got stuck)
    stack_lock_del = stack_lock.delete().where(
        stack_lock.c.stack_id.in_(stack_ids))
    engine.execute(stack_lock_del)
    # delete stack tags
    stack_tag_del = stack_tag.delete().where(
        stack_tag.c.stack_id.in_(stack_ids))
    engine.execute(stack_tag_del)
    # delete resource_data
    res_where = sqlalchemy.select([resource.c.id]).where(
        resource.c.stack_id.in_(stack_ids))
    res_data_del = resource_data.delete().where(
        resource_data.c.resource_id.in_(res_where))
    engine.execute(res_data_del)
    # clean up any sync_points that may have lingered
    sync_del = syncpoint.delete().where(
        syncpoint.c.stack_id.in_(stack_ids))
    engine.execute(sync_del)

    # get rsrc_prop_data_ids to delete
    rsrc_prop_data_where = sqlalchemy.select(
        [resource.c.rsrc_prop_data_id]).where(
            resource.c.stack_id.in_(stack_ids))
    rsrc_prop_data_ids = set(
        [i[0] for i in list(engine.execute(rsrc_prop_data_where))])
    rsrc_prop_data_where = sqlalchemy.select(
        [resource.c.attr_data_id]).where(
            resource.c.stack_id.in_(stack_ids))
    rsrc_prop_data_ids.update(
        [i[0] for i in list(engine.execute(rsrc_prop_data_where))])
    rsrc_prop_data_where = sqlalchemy.select(
        [event.c.rsrc_prop_data_id]).where(
            event.c.stack_id.in_(stack_ids))
    rsrc_prop_data_ids.update(
        [i[0] for i in list(engine.execute(rsrc_prop_data_where))])
    # delete events
    event_del = event.delete().where(event.c.stack_id.in_(stack_ids))
    engine.execute(event_del)
    # delete resources (normally there shouldn't be any)
    res_del = resource.delete().where(resource.c.stack_id.in_(stack_ids))
    engine.execute(res_del)
    # delete resource_properties_data
    if rsrc_prop_data_ids:  # keep rpd's in events
        rsrc_prop_data_where = sqlalchemy.select(
            [event.c.rsrc_prop_data_id]).where(
                event.c.rsrc_prop_data_id.in_(rsrc_prop_data_ids))
        ids = list(engine.execute(rsrc_prop_data_where))
        rsrc_prop_data_ids.difference_update([i[0] for i in ids])
    if rsrc_prop_data_ids:  # keep rpd's in resources
        rsrc_prop_data_where = sqlalchemy.select(
            [resource.c.rsrc_prop_data_id]).where(
                resource.c.rsrc_prop_data_id.in_(rsrc_prop_data_ids))
        ids = list(engine.execute(rsrc_prop_data_where))
        rsrc_prop_data_ids.difference_update([i[0] for i in ids])
    if rsrc_prop_data_ids:  # delete if we have any
        rsrc_prop_data_del = resource_properties_data.delete().where(
            resource_properties_data.c.id.in_(rsrc_prop_data_ids))
        engine.execute(rsrc_prop_data_del)
    # delete the stacks
    stack_del = stack.delete().where(stack.c.id.in_(stack_ids))
    engine.execute(stack_del)
    # delete orphaned raw templates
    raw_template_ids = [i[1] for i in stack_infos if i[1] is not None]
    raw_template_ids.extend(i[2] for i in stack_infos if i[2] is not None)
    if raw_template_ids:  # keep those still referenced
        raw_tmpl_sel = sqlalchemy.select([stack.c.raw_template_id]).where(
            stack.c.raw_template_id.in_(raw_template_ids))
        raw_tmpl = [i[0] for i in engine.execute(raw_tmpl_sel)]
        raw_template_ids = set(raw_template_ids) - set(raw_tmpl)
    if raw_template_ids:  # keep those still referenced (previous tmpl)
        raw_tmpl_sel = sqlalchemy.select(
            [stack.c.prev_raw_template_id]).where(
            stack.c.prev_raw_template_id.in_(raw_template_ids))
        raw_tmpl = [i[0] for i in engine.execute(raw_tmpl_sel)]
        raw_template_ids = raw_template_ids - set(raw_tmpl)
    if raw_template_ids:  # delete raw_templates if we have any
        raw_tmpl_file_sel = sqlalchemy.select(
            [raw_template.c.files_id]).where(
                raw_template.c.id.in_(raw_template_ids))
        raw_tmpl_file_ids = [i[0] for i in engine.execute(
            raw_tmpl_file_sel)]
        raw_templ_del = raw_template.delete().where(
            raw_template.c.id.in_(raw_template_ids))
        engine.execute(raw_templ_del)
        if raw_tmpl_file_ids:  # keep _files still referenced
            raw_tmpl_file_sel = sqlalchemy.select(
                [raw_template.c.files_id]).where(
                    raw_template.c.files_id.in_(raw_tmpl_file_ids))
            raw_tmpl_files = [i[0] for i in engine.execute(
                raw_tmpl_file_sel)]
            raw_tmpl_file_ids = set(raw_tmpl_file_ids) \
                - set(raw_tmpl_files)
        if raw_tmpl_file_ids:  # delete _files if we have any
            raw_tmpl_file_del = raw_template_files.delete().where(
                raw_template_files.c.id.in_(raw_tmpl_file_ids))
            engine.execute(raw_tmpl_file_del)
    # purge any user creds that are no longer referenced
    user_creds_ids = [i[3] for i in stack_infos if i[3] is not None]
    if user_creds_ids:  # keep those still referenced
        user_sel = sqlalchemy.select([stack.c.user_creds_id]).where(
            stack.c.user_creds_id.in_(user_creds_ids))
        users = [i[0] for i in engine.execute(user_sel)]
        user_creds_ids = set(user_creds_ids) - set(users)
    if user_creds_ids:  # delete if we have any
        usr_creds_del = user_creds.delete().where(
            user_creds.c.id.in_(user_creds_ids))
        engine.execute(usr_creds_del)


def sync_point_delete_all_by_stack_and_traversal(context, stack_id,
                                                 traversal_id):
    rows_deleted = context.session.query(models.SyncPoint).filter_by(
        stack_id=stack_id, traversal_id=traversal_id).delete()
    return rows_deleted


@oslo_db_api.wrap_db_retry(max_retries=3, retry_on_deadlock=True,
                           retry_interval=0.5, inc_retry_interval=True)
def sync_point_create(context, values):
    values['entity_id'] = str(values['entity_id'])
    sync_point_ref = models.SyncPoint()
    sync_point_ref.update(values)
    sync_point_ref.save(context.session)
    return sync_point_ref


def sync_point_get(context, entity_id, traversal_id, is_update):
    entity_id = str(entity_id)
    return context.session.query(models.SyncPoint).get(
        (entity_id, traversal_id, is_update)
    )


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


def db_sync(engine, version=None):
    """Migrate the database to `version` or the most recent version."""
    if version is not None and int(version) < db_version(engine):
        raise exception.Error(_("Cannot migrate to lower schema version."))

    return migration.db_sync(engine, version=version)


def db_version(engine):
    """Display the current database version."""
    return migration.db_version(engine)


def _crypt_action(encrypt):
    if encrypt:
        return _('encrypt')
    return _('decrypt')


def _db_encrypt_or_decrypt_template_params(
        ctxt, encryption_key, encrypt=False, batch_size=50, verbose=False):
    from heat.engine import template
    session = ctxt.session
    excs = []
    query = session.query(models.RawTemplate)
    template_batches = _get_batch(
        session, ctxt=ctxt, query=query, model=models.RawTemplate,
        batch_size=batch_size)
    next_batch = list(itertools.islice(template_batches, batch_size))
    while next_batch:
        with session.begin(subtransactions=True):
            for raw_template in next_batch:
                try:
                    if verbose:
                        LOG.info("Processing raw_template %s...",
                                 raw_template.id)
                    env = raw_template.environment
                    needs_update = False

                    # using "in env.keys()" so an exception is raised
                    # if env is something weird like a string.
                    if env is None or 'parameters' not in env.keys():
                        continue
                    if 'encrypted_param_names' in env:
                        encrypted_params = env['encrypted_param_names']
                    else:
                        encrypted_params = []

                    if encrypt:
                        tmpl = template.Template.load(
                            ctxt, raw_template.id, raw_template)
                        param_schemata = tmpl.param_schemata()
                        if not param_schemata:
                            continue

                        for param_name, param_val in env['parameters'].items():
                            if (param_name in encrypted_params or
                                    param_name not in param_schemata or
                                    not param_schemata[param_name].hidden):
                                continue
                            encrypted_val = crypt.encrypt(
                                six.text_type(param_val), encryption_key)
                            env['parameters'][param_name] = encrypted_val
                            encrypted_params.append(param_name)
                            needs_update = True
                        if needs_update:
                            newenv = env.copy()
                            newenv['encrypted_param_names'] = encrypted_params
                    else:  # decrypt
                        for param_name in encrypted_params:
                            method, value = env['parameters'][param_name]
                            decrypted_val = crypt.decrypt(method, value,
                                                          encryption_key)
                            env['parameters'][param_name] = decrypted_val
                            needs_update = True
                        if needs_update:
                            newenv = env.copy()
                            newenv['encrypted_param_names'] = []

                    if needs_update:
                        raw_template_update(ctxt, raw_template.id,
                                            {'environment': newenv})
                except Exception as exc:
                    LOG.exception('Failed to %(crypt_action)s parameters '
                                  'of raw template %(id)d',
                                  {'id': raw_template.id,
                                   'crypt_action': _crypt_action(encrypt)})
                    excs.append(exc)
                    continue
                finally:
                    if verbose:
                        LOG.info("Finished %(crypt_action)s processing of "
                                 "raw_template %(id)d.",
                                 {'id': raw_template.id,
                                  'crypt_action': _crypt_action(encrypt)})
        next_batch = list(itertools.islice(template_batches, batch_size))
    return excs


def _db_encrypt_or_decrypt_resource_prop_data_legacy(
        ctxt, encryption_key, encrypt=False, batch_size=50, verbose=False):
    session = ctxt.session
    excs = []

    # Older resources may have properties_data in the legacy column,
    # so update those as needed
    query = session.query(models.Resource).filter(
        models.Resource.properties_data_encrypted.isnot(encrypt))
    resource_batches = _get_batch(
        session=session, ctxt=ctxt, query=query, model=models.Resource,
        batch_size=batch_size)
    next_batch = list(itertools.islice(resource_batches, batch_size))
    while next_batch:
        with session.begin(subtransactions=True):
            for resource in next_batch:
                if not resource.properties_data:
                    continue
                try:
                    if verbose:
                        LOG.info("Processing resource %s...",
                                 resource.id)
                    if encrypt:
                        result = crypt.encrypted_dict(resource.properties_data,
                                                      encryption_key)
                    else:
                        result = crypt.decrypted_dict(resource.properties_data,
                                                      encryption_key)
                    resource_update(ctxt, resource.id,
                                    {'properties_data': result,
                                     'properties_data_encrypted': encrypt},
                                    resource.atomic_key)
                except Exception as exc:
                    LOG.exception('Failed to %(crypt_action)s '
                                  'properties_data of resource %(id)d' %
                                  {'id': resource.id,
                                   'crypt_action': _crypt_action(encrypt)})
                    excs.append(exc)
                    continue
                finally:
                    if verbose:
                        LOG.info("Finished processing resource %s.",
                                 resource.id)
        next_batch = list(itertools.islice(resource_batches, batch_size))
    return excs


def _db_encrypt_or_decrypt_resource_prop_data(
        ctxt, encryption_key, encrypt=False, batch_size=50, verbose=False):
    session = ctxt.session
    excs = []

    # Older resources may have properties_data in the legacy column,
    # so update those as needed
    query = session.query(models.ResourcePropertiesData).filter(
        models.ResourcePropertiesData.encrypted.isnot(encrypt))
    rpd_batches = _get_batch(
        session=session, ctxt=ctxt, query=query,
        model=models.ResourcePropertiesData, batch_size=batch_size)
    next_batch = list(itertools.islice(rpd_batches, batch_size))
    while next_batch:
        with session.begin(subtransactions=True):
            for rpd in next_batch:
                if not rpd.data:
                    continue
                try:
                    if verbose:
                        LOG.info("Processing resource_properties_data "
                                 "%s...", rpd.id)
                    if encrypt:
                        result = crypt.encrypted_dict(rpd.data,
                                                      encryption_key)
                    else:
                        result = crypt.decrypted_dict(rpd.data,
                                                      encryption_key)
                    rpd.update({'data': result,
                                'encrypted': encrypt})
                except Exception as exc:
                    LOG.exception(
                        "Failed to %(crypt_action)s "
                        "data of resource_properties_data %(id)d" %
                        {'id': rpd.id,
                         'crypt_action': _crypt_action(encrypt)})
                    excs.append(exc)
                    continue
                finally:
                    if verbose:
                        LOG.info(
                            "Finished processing resource_properties_data"
                            " %s.", rpd.id)
        next_batch = list(itertools.islice(rpd_batches, batch_size))
    return excs


def db_encrypt_parameters_and_properties(ctxt, encryption_key, batch_size=50,
                                         verbose=False):
    """Encrypt parameters and properties for all templates in db.

    :param ctxt: RPC context
    :param encryption_key: key that will be used for parameter and property
                           encryption
    :param batch_size: number of templates requested from db in each iteration.
                       50 means that heat requests 50 templates, encrypt them
                       and proceed with next 50 items.
    :param verbose: log an INFO message when processing of each raw_template or
                    resource begins or ends
    :return: list of exceptions encountered during encryption
    """
    excs = []
    excs.extend(_db_encrypt_or_decrypt_template_params(
        ctxt, encryption_key, True, batch_size, verbose))
    excs.extend(_db_encrypt_or_decrypt_resource_prop_data(
        ctxt, encryption_key, True, batch_size, verbose))
    excs.extend(_db_encrypt_or_decrypt_resource_prop_data_legacy(
        ctxt, encryption_key, True, batch_size, verbose))
    return excs


def db_decrypt_parameters_and_properties(ctxt, encryption_key, batch_size=50,
                                         verbose=False):
    """Decrypt parameters and properties for all templates in db.

    :param ctxt: RPC context
    :param encryption_key: key that will be used for parameter and property
                           decryption
    :param batch_size: number of templates requested from db in each iteration.
                       50 means that heat requests 50 templates, encrypt them
                       and proceed with next 50 items.
    :param verbose: log an INFO message when processing of each raw_template or
                    resource begins or ends
    :return: list of exceptions encountered during decryption
    """
    excs = []
    excs.extend(_db_encrypt_or_decrypt_template_params(
        ctxt, encryption_key, False, batch_size, verbose))
    excs.extend(_db_encrypt_or_decrypt_resource_prop_data(
        ctxt, encryption_key, False, batch_size, verbose))
    excs.extend(_db_encrypt_or_decrypt_resource_prop_data_legacy(
        ctxt, encryption_key, False, batch_size, verbose))
    return excs


def db_properties_data_migrate(ctxt, batch_size=50):
    """Migrate properties data from legacy columns to new location in db.

    :param ctxt: RPC context
    :param batch_size: number of templates requested from db in each iteration.
                       50 means that heat requests 50 templates, encrypt them
                       and proceed with next 50 items.
    """
    session = ctxt.session

    query = session.query(models.Resource).filter(and_(
        models.Resource.properties_data.isnot(None),
        models.Resource.rsrc_prop_data_id.is_(None)))
    resource_batches = _get_batch(
        session=session, ctxt=ctxt, query=query,
        model=models.Resource, batch_size=batch_size)
    next_batch = list(itertools.islice(resource_batches, batch_size))
    while next_batch:
        with session.begin():
            for resource in next_batch:
                try:
                    encrypted = resource.properties_data_encrypted
                    if encrypted is None:
                        LOG.warning(
                            'Unexpected: resource.encrypted is None for '
                            'resource id %s for legacy '
                            'resource.properties_data, assuming False.',
                            resource.id)
                        encrypted = False
                    rsrc_prop_data = resource_prop_data_create(
                        ctxt, {'encrypted': encrypted,
                               'data': resource.properties_data})
                    resource_update(ctxt, resource.id,
                                    {'properties_data_encrypted': None,
                                     'properties_data': None,
                                     'rsrc_prop_data_id': rsrc_prop_data.id},
                                    resource.atomic_key)
                except Exception:
                    LOG.exception('Failed to migrate properties_data for '
                                  'resource %d', resource.id)
                    continue
        next_batch = list(itertools.islice(resource_batches, batch_size))

    query = session.query(models.Event).filter(and_(
        models.Event.resource_properties.isnot(None),
        models.Event.rsrc_prop_data_id.is_(None)))
    event_batches = _get_batch(
        session=session, ctxt=ctxt, query=query,
        model=models.Event, batch_size=batch_size)
    next_batch = list(itertools.islice(event_batches, batch_size))
    while next_batch:
        with session.begin():
            for event in next_batch:
                try:
                    prop_data = event.resource_properties
                    rsrc_prop_data = resource_prop_data_create(
                        ctxt, {'encrypted': False,
                               'data': prop_data})
                    event.update({'resource_properties': None,
                                  'rsrc_prop_data_id': rsrc_prop_data.id})
                except Exception:
                    LOG.exception('Failed to migrate resource_properties '
                                  'for event %d', event.id)
                    continue
        next_batch = list(itertools.islice(event_batches, batch_size))


def _get_batch(session, ctxt, query, model, batch_size=50):
    last_batch_marker = None
    while True:
        results = _paginate_query(
            context=ctxt, query=query, model=model, limit=batch_size,
            marker=last_batch_marker).all()
        if not results:
            break
        else:
            for result in results:
                yield result
            last_batch_marker = results[-1].id


def reset_stack_status(context, stack_id, stack=None):
    session = context.session
    if stack is None:
        stack = session.query(models.Stack).get(stack_id)

    if stack is None:
        raise exception.NotFound(_('Stack with id %s not found') % stack_id)

    with session.begin():
        query = session.query(models.Resource).filter_by(
            status='IN_PROGRESS', stack_id=stack_id)
        query.update({'status': 'FAILED',
                      'status_reason': 'Stack status manually reset',
                      'engine_id': None})

        query = session.query(models.ResourceData)
        query = query.join(models.Resource)
        query = query.filter_by(stack_id=stack_id)
        query = query.filter(
            models.ResourceData.key.in_(heat_environment.HOOK_TYPES))
        data_ids = [data.id for data in query]

        if data_ids:
            query = session.query(models.ResourceData)
            query = query.filter(models.ResourceData.id.in_(data_ids))
            query.delete(synchronize_session='fetch')

    query = session.query(models.Stack).filter_by(owner_id=stack_id)
    for child in query:
        reset_stack_status(context, child.id, child)

    with session.begin():
        if stack.status == 'IN_PROGRESS':
            stack.status = 'FAILED'
            stack.status_reason = 'Stack status manually reset'

        session.query(
            models.StackLock
        ).filter_by(stack_id=stack_id).delete()
