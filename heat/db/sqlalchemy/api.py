# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

'''Implementation of SQLAlchemy backend.'''

from nova import utils
from heat.db.sqlalchemy import models
from heat.db.sqlalchemy.session import get_session

def model_query(context, *args, **kwargs):
    """Query helper that accounts for context's `read_deleted` field.

    :param context: context to query under
    :param session: if present, the session to use
    :param read_deleted: if present, overrides context's read_deleted field.
    :param project_only: if present and context is user-type, then restrict
            query to match the context's project_id.
    """
    session = kwargs.get('session') or get_session()
    read_deleted = kwargs.get('read_deleted') or context.read_deleted
    project_only = kwargs.get('project_only')

    query = session.query(*args)

    if read_deleted == 'no':
        query = query.filter_by(deleted=False)
    elif read_deleted == 'yes':
        pass  # omit the filter to include deleted and active
    elif read_deleted == 'only':
        query = query.filter_by(deleted=True)
    else:
        raise Exception(
                _("Unrecognized read_deleted value '%s'") % read_deleted)

    if project_only and is_user_context(context):
        query = query.filter_by(project_id=context.project_id)

    return query

def raw_template_get(context, template_id):
    result = model_query(context, models.RawTemplate).\
                        filter_by(id=template_id).first()

    if not result:
        raise Exception("raw template with id %s not found" % template_id)

    return result

def raw_template_get_all(context):
    results = model_query(context, models.RawTemplate).all()

    if not results:
        raise Exception('no raw templates were found')
    
    return results

def raw_template_create(context, values):
    raw_template_ref = models.RawTemplate()
    raw_template_ref.update(values)
    raw_template_ref.save()
    return raw_template_ref

def parsed_template_get(context, template_id):
    result = model_query(context, models.ParsedTemplate).\
                        filter_by(id=template_id).first()

    if not result:
        raise Exception("parsed template with id %s not found" % template_id)

    return result

def parsed_template_get_all(context):
    results = model_query(context, models.ParsedTemplate).all()

    if not results:
        raise Exception('no parsed templates were found')
    
    return results

def parsed_template_create(context, values):
    parsed_template_ref = models.ParsedTemplate()
    parsed_template_ref.update(values)
    parsed_template_ref.save()
    return parsed_template_ref

def resource_get(context, resource_id):
    result = model_query(context, models.Resource).\
                        filter_by(id=resource_id).first()

    if not result:
        raise Exception("resource with id %s not found" % resource_id)

    return result

def resource_get_all(context):
    results = model_query(context, models.Resource).all()

    if not results:
        raise Exception('no resources were found')
    
    return results

def resource_create(context, values):
    resource_ref = models.Resource()
    resource_ref.update(values)
    resource_ref.save()
    return resource_ref

def stack_get(context, stack_id):
    result = model_query(context, models.Stack).\
                        filter_by(id=stack_id).first()

    if not result:
        raise Exception("stack with id %s not found" % stack_id)

    return result

def stack_get_all(context):
    results = model_query(context, models.Stack).all()

    if not results:
        raise Exception('no stacks were found')
    
    return results

def stack_create(context, values):
    stack_ref = models.Stack()
    stack_ref.update(values)
    stack_ref.save()
    return stack_ref

def event_get(context, event_id):
    result = model_query(context, models.Event).\
                        filter_by(id=event_id).first()

    if not result:
        raise Exception("event with id %s not found" % event_id)

    return result

def event_get_all(context):
    results = model_query(context, models.Event).all()

    if not results:
        raise Exception('no events were found')
    
    return results

def event_get_all_by_stack(context, stack_id):
    results = model_query(context, models.Event).\
                        filter_by(stack_id).all()

    if not results:
        raise Exception("no events for stack_id %s were found" % stack_id)
    
    return results

def event_create(context, values):
    event_ref = models.Event()
    event_ref.update(values)
    event_ref.save()
    return event_ref
