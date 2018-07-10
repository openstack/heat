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

import random
import string
import uuid

import fixtures
from oslo_config import cfg
from oslo_db import options
from oslo_serialization import jsonutils
import sqlalchemy

from heat.common import context
from heat.db.sqlalchemy import api as db_api
from heat.db.sqlalchemy import models
from heat.engine import environment
from heat.engine import node_data
from heat.engine import resource
from heat.engine import stack
from heat.engine import template

get_engine = db_api.get_engine


class UUIDStub(object):
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.uuid4 = uuid.uuid4
        uuid.uuid4 = lambda: self.value

    def __exit__(self, *exc_info):
        uuid.uuid4 = self.uuid4


def random_name():
    return ''.join(random.choice(string.ascii_uppercase)
                   for x in range(10))


def setup_dummy_db():
    options.cfg.set_defaults(options.database_opts, sqlite_synchronous=False)
    # Uncomment to log SQL
    # options.cfg.set_defaults(options.database_opts, connection_debug=100)
    options.set_defaults(cfg.CONF, connection="sqlite://")
    engine = get_engine()
    models.BASE.metadata.create_all(engine)
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
                  password='', roles=None, user_id=None,
                  trust_id=None, region_name=None, is_admin=False):
    roles = roles or []
    return context.RequestContext.from_dict({
        'tenant_id': tenant_id,
        'tenant': 'test_tenant',
        'username': user,
        'user_id': user_id,
        'password': password,
        'roles': roles,
        'is_admin': is_admin,
        'auth_url': 'http://server.test:5000/v2.0',
        'auth_token': 'abcd1234',
        'trust_id': trust_id,
        'region_name': region_name
    })


def parse_stack(t, params=None, files=None, stack_name=None,
                stack_id=None, timeout_mins=None,
                cache_data=None, tags=None):
    params = params or {}
    files = files or {}
    ctx = dummy_context()
    templ = template.Template(t, files=files,
                              env=environment.Environment(params))
    templ.store(ctx)
    if stack_name is None:
        stack_name = random_name()
    if cache_data is not None:
        cache_data = {n: node_data.NodeData.from_dict(d)
                      for n, d in cache_data.items()}
    stk = stack.Stack(ctx, stack_name, templ, stack_id=stack_id,
                      timeout_mins=timeout_mins,
                      cache_data=cache_data, tags=tags)
    stk.store()
    return stk


def update_stack(stk, new_t, params=None, files=None):
    ctx = dummy_context()
    templ = template.Template(new_t, files=files,
                              env=environment.Environment(params))
    updated_stack = stack.Stack(ctx, 'updated_stack', templ)

    stk.update(updated_stack)


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
            stk, res, short_id = str(physical_name).rsplit('-', 2)
        except ValueError:
            return False

        if len(short_id) != len(self.mock_short_id):
            return False

        # stack name may have been truncated
        if (not isinstance(self.stack, PhysName) and
                3 < len(stk) < len(self.stack)):
            our_stk = self.stack[:2] + '-' + self.stack[3 - len(stk):]
        else:
            our_stk = self.stack

        return (stk == our_stk) and (res == self.res)

    def __hash__(self):
        return hash(self.stack) ^ hash(self.res)

    def __ne__(self, physical_name):
        return not self.__eq__(physical_name)

    def __repr__(self):
        return self._physname


def recursive_sort(obj):
    """Recursively sort list in iterables for comparison."""
    if isinstance(obj, dict):
        for v in obj.values():
            recursive_sort(v)
    elif isinstance(obj, list):
        obj.sort()
        for i in obj:
            recursive_sort(i)
    return obj


class JsonRepr(object):
    """Comparison class used to check the deserialisation of a JSON string.

    If a dict is dumped to json, the order is undecided, so load the string
    back to an object for comparison.
    """

    def __init__(self, data):
        """Initialise with the unserialised data."""
        self._data = data

    def __eq__(self, json_data):
        return self._data == jsonutils.loads(json_data)

    def __ne__(self, json_data):
        return not self.__eq__(json_data)

    def __repr__(self):
        return jsonutils.dumps(self._data)


class ForeignKeyConstraintFixture(fixtures.Fixture):
    def __init__(self, sqlite_fk=True):
        self.enable_fkc = sqlite_fk

    def _setUp(self):
        new_context = db_api.db_context.make_new_manager()
        new_context.configure(sqlite_fk=self.enable_fkc)

        self.useFixture(fixtures.MockPatchObject(db_api, '_facade', None))
        self.addCleanup(db_api.db_context.patch_factory(new_context._factory))


class AnyInstance(object):
    """Comparator for validating allowed instance type."""

    def __init__(self, allowed_type):
        self._allowed_type = allowed_type

    def __eq__(self, other):
        return isinstance(other, self._allowed_type)

    def __ne__(self, other):
        return not self.__eq__(other)
