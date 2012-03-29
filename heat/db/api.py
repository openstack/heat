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

'''
Interface for database access.

Usage:

    >>> from heat import db
    >>> db.event_get(context, event_id)
    # Event object received

The underlying driver is loaded as a :class:`LazyPluggable`. SQLAlchemy is
currently the only supported backend.
'''

from nova import flags
from nova.openstack.common import cfg
from nova import utils


db_opts = [
    cfg.StrOpt('db_backend', default='db', help='The backend to use for db'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(db_opts)

IMPL = utils.LazyPluggable('db_backend', db='heat.db.sqlalchemy.api')


def raw_template_get(context, template_id):
    return IMPL.raw_template_get(context, template_id)

def raw_template_get_all(context):
    return IMPL.raw_template_get_all(context)

def raw_template_create(context, values):
    return IMPL.raw_template_create(context, values)


def parsed_template_get(context, template_id):
    return IMPL.parsed_template_get(context, template_id)

def parsed_template_get_all(context):
    return IMPL.parsed_template_get_all(context)

def parsed_template_create(context, values):
    return IMPL.parsed_template_create(context, values)


def state_get(context, state_id):
    return IMPL.state_get(context, state_id)

def state_get_all(context):
    return IMPL.state_get_all(context)

def state_create(context, values):
    return IMPL.state_create(context, values)


def event_get(context, event_id):
    return IMPL.event_get(context, event_id)

def event_get_all(context):
    return IMPL.event_get_all(context)

def event_get_all_by_stack(context, stack_id):
    return IMPL.event_get_all_by_stack(context, stack_id)

def event_create(context, values):
    return IMPL.event_create(context, values)
