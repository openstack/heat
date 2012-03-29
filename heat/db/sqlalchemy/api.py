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

from nova.db.sqlalchemy.session import get_session
from nova import flags
from nova import utils

FLAGS = flags.FLAGS

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

# a big TODO
def raw_template_get(context, template_id):
    return 'test return value'

def raw_template_get_all(context):
    pass

def raw_template_create(context, values):
    pass


def parsed_template_get(context, template_id):
    pass

def parsed_template_get_all(context):
    pass

def parsed_template_create(context, values):
    pass


def state_get(context, state_id):
    pass

def state_get_all(context):
    pass

def state_create(context, values):
    pass


def event_get(context, event_id):
    pass

def event_get_all(context):
    pass

def event_get_all_by_stack(context, stack_id):
    pass

def event_create(context, values):
    pass
