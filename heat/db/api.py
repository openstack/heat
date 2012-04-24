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

The underlying driver is loaded . SQLAlchemy is currently the only
supported backend.
'''
import heat.utils
from heat.openstack.common import utils
from heat.openstack.common import cfg
from heat.common import config
import heat.utils

SQL_CONNECTION = 'sqlite:///heat-test.db/'
SQL_IDLE_TIMEOUT = 3600
db_opts = [
    cfg.StrOpt('db_backend',
               default='sqlalchemy',
               help='The backend to use for db'),
    ]

conf = config.HeatEngineConfigOpts()
conf.db_backend = 'heat.db.sqlalchemy.api'
IMPL = heat.utils.LazyPluggable('db_backend',
                           sqlalchemy='heat.db.sqlalchemy.api')
def configure(conf):
    global SQL_CONNECTION
    global SQL_IDLE_TIMEOUT
    SQL_CONNECTION = conf.sql_connection
    SQL_IDLE_TIMEOUT = conf.sql_idle_timeout



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


def resource_get(context, resource_id):
    return IMPL.resource_get(context, resource_id)


def resource_get_all(context):
    return IMPL.resource_get_all(context)


def resource_create(context, values):
    return IMPL.resource_create(context, values)


def resource_get_all_by_stack(context, stack_id):
    return IMPL.resource_get_all_by_stack(context, stack_id)


def resource_get_by_name_and_stack(context, resource_name, stack_id):
    return IMPL.resource_get_by_name_and_stack(context,
                                               resource_name, stack_id)


def stack_get(context, stack_id):
    return IMPL.stack_get(context, stack_id)


def stack_get_all(context):
    return IMPL.stack_get_all(context)


def stack_create(context, values):
    return IMPL.stack_create(context, values)


def stack_delete(context, stack_name):
    return IMPL.stack_delete(context, stack_name)


def event_get(context, event_id):
    return IMPL.event_get(context, event_id)


def event_get_all(context):
    return IMPL.event_get_all(context)


def event_get_all_by_stack(context, stack_id):
    return IMPL.event_get_all_by_stack(context, stack_id)


def event_create(context, values):
    return IMPL.event_create(context, values)
