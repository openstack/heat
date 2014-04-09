
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

import functools
import random
import string
import sys
import uuid

from oslo.config import cfg
import sqlalchemy

from heat.common import context
from heat.common import exception
from heat.db import api as db_api
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.openstack.common.db.sqlalchemy import session

get_engine = session.get_engine


class UUIDStub(object):
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.uuid4 = uuid.uuid4
        uuid_stub = lambda: self.value
        uuid.uuid4 = uuid_stub

    def __exit__(self, *exc_info):
        uuid.uuid4 = self.uuid4


def random_name():
    return ''.join(random.choice(string.ascii_uppercase)
                   for x in range(10))


def stack_delete_after(test_fn):
    """
    Decorator which calls test class self.stack.delete()
    to ensure tests clean up their stacks regardless of test success/failure
    """
    @functools.wraps(test_fn)
    def wrapped_test(test_case, *args, **kwargs):
        def delete_stack():
            stack = getattr(test_case, 'stack', None)
            if stack is not None and stack.id is not None:
                stack.delete()

        try:
            test_fn(test_case, *args, **kwargs)
        except:
            exc_class, exc_val, exc_tb = sys.exc_info()
            try:
                delete_stack()
            finally:
                raise exc_class, exc_val, exc_tb
        else:
            delete_stack()

    return wrapped_test


def wr_delete_after(test_fn):
    """
    Decorator which calls test class self.wr.destroy()
    to ensure tests clean up their watchrule regardless of test success/failure
    Used by tests which create watchrule objects directly to cleanup correctly
    self.wr can be either a single watchrule, or a list of several watchrules
    """
    @functools.wraps(test_fn)
    def wrapped_test(test_case, *args, **kwargs):

        def delete_wrs():
            wr = getattr(test_case, 'wr', None)
            try:
                for w in wr:
                    delete_wr(w)
            except TypeError:
                delete_wr(wr)

        def delete_wr(w):
            if w.id is not None:
                try:
                    w.destroy()
                except exception.NotFound:
                    pass
        try:
            test_fn(test_case, *args, **kwargs)
        except:
            exc_class, exc_val, exc_tb = sys.exc_info()
            try:
                delete_wrs()
            finally:
                raise exc_class, exc_val, exc_tb
        else:
            delete_wrs()

    return wrapped_test


def setup_dummy_db():
    cfg.CONF.set_default('sqlite_synchronous', False)
    session.set_defaults(sql_connection="sqlite://", sqlite_db='heat.db')
    db_api.db_sync()
    engine = get_engine()
    engine.connect()


def reset_dummy_db():
    engine = get_engine()
    meta = sqlalchemy.MetaData()
    meta.reflect(bind=engine)

    for table in reversed(meta.sorted_tables):
        if table.name == 'migrate_version':
            continue
        engine.execute(table.delete())


def dummy_context(user='test_username', tenant_id='test_tenant_id',
                  password='password', roles=[], user_id=None):
    return context.RequestContext.from_dict({
        'tenant_id': tenant_id,
        'tenant': 'test_tenant',
        'username': user,
        'user_id': user_id,
        'password': password,
        'roles': roles,
        'is_admin': False,
        'auth_url': 'http://server.test:5000/v2.0',
        'auth_token': 'abcd1234'
    })


def parse_stack(t, params={}, stack_name='test_stack', stack_id=None,
                timeout_mins=None):
    ctx = dummy_context()
    template = parser.Template(t)
    stack = parser.Stack(ctx, stack_name, template,
                         environment.Environment(params), stack_id,
                         timeout_mins=timeout_mins)
    stack.store()

    return stack


class PhysName(object):

    mock_short_id = 'x' * 12

    def __init__(self, stack_name, resource_name, limit=255):
        name = '%s-%s-%s' % (stack_name,
                             resource_name,
                             self.mock_short_id)
        self._physname = resource.Resource.reduce_physical_resource_name(
            name, limit)
        self.stack, self.res, self.sid = self._physname.rsplit('-', 2)

    def __eq__(self, physical_name):
        try:
            stack, res, short_id = str(physical_name).rsplit('-', 2)
        except ValueError:
            return False

        if len(short_id) != len(self.mock_short_id):
            return False

        # ignore the stack portion of the name, as it may have been truncated
        return res == self.res

    def __ne__(self, physical_name):
        return not self.__eq__(physical_name)

    def __repr__(self):
        return self._physname
