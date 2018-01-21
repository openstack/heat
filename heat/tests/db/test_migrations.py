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

"""
Tests for database migrations. This test case reads the configuration
file test_migrations.conf for database connection settings
to use in the tests. For each connection found in the config file,
the test case runs a series of test cases to ensure that migrations work
properly both upgrading and downgrading, and that no data loss occurs
if possible.
"""

import datetime
import fixtures
import os
import uuid

from migrate.versioning import repository
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslotest import base as test_base
import six
import sqlalchemy
import testtools

from heat.db.sqlalchemy import migrate_repo
from heat.db.sqlalchemy import migration
from heat.db.sqlalchemy import models
from heat.tests import common


class DBNotAllowed(Exception):
    pass


class BannedDBSchemaOperations(fixtures.Fixture):
    """Ban some operations for migrations"""
    def __init__(self, banned_resources=None):
        super(BannedDBSchemaOperations, self).__init__()
        self._banned_resources = banned_resources or []

    @staticmethod
    def _explode(resource, op):
        print('%s.%s()' % (resource, op))
        raise DBNotAllowed(
            'Operation %s.%s() is not allowed in a database migration' % (
                resource, op))

    def setUp(self):
        super(BannedDBSchemaOperations, self).setUp()
        for thing in self._banned_resources:
            self.useFixture(fixtures.MonkeyPatch(
                'sqlalchemy.%s.drop' % thing,
                lambda *a, **k: self._explode(thing, 'drop')))
            self.useFixture(fixtures.MonkeyPatch(
                'sqlalchemy.%s.alter' % thing,
                lambda *a, **k: self._explode(thing, 'alter')))


class TestBannedDBSchemaOperations(testtools.TestCase):
    def test_column(self):
        column = sqlalchemy.Column()
        with BannedDBSchemaOperations(['Column']):
            self.assertRaises(DBNotAllowed, column.drop)
            self.assertRaises(DBNotAllowed, column.alter)

    def test_table(self):
        table = sqlalchemy.Table()
        with BannedDBSchemaOperations(['Table']):
            self.assertRaises(DBNotAllowed, table.drop)
            self.assertRaises(DBNotAllowed, table.alter)


class HeatMigrationsCheckers(test_migrations.WalkVersionsMixin,
                             common.FakeLogMixin):
    """Test sqlalchemy-migrate migrations."""

    snake_walk = False
    downgrade = False

    @property
    def INIT_VERSION(self):
        return migration.INIT_VERSION

    @property
    def REPOSITORY(self):
        migrate_file = migrate_repo.__file__
        return repository.Repository(
            os.path.abspath(os.path.dirname(migrate_file))
        )

    @property
    def migration_api(self):
        temp = __import__('oslo_db.sqlalchemy.migration', globals(),
                          locals(), ['versioning_api'], 0)
        return temp.versioning_api

    @property
    def migrate_engine(self):
        return self.engine

    def migrate_up(self, version, with_data=False):
        """Check that migrations don't cause downtime.

        Schema migrations can be done online, allowing for rolling upgrades.
        """
        # NOTE(xek): This is a list of migrations where we allow dropping
        # things. The rules for adding exceptions are very very specific.
        # Chances are you don't meet the critera.
        # Reviewers: DO NOT ALLOW THINGS TO BE ADDED HERE
        exceptions = [
            64,  # drop constraint
            86,  # drop watch_rule/watch_data tables
        ]
        # Reviewers: DO NOT ALLOW THINGS TO BE ADDED HERE

        # NOTE(xek): We start requiring things be additive in
        # liberty, so ignore all migrations before that point.
        LIBERTY_START = 63

        if version >= LIBERTY_START and version not in exceptions:
            banned = ['Table', 'Column']
        else:
            banned = None
        with BannedDBSchemaOperations(banned):
            super(HeatMigrationsCheckers, self).migrate_up(version, with_data)

    def test_walk_versions(self):
        self.walk_versions(self.snake_walk, self.downgrade)

    def assertColumnExists(self, engine, table, column):
        t = utils.get_table(engine, table)
        self.assertIn(column, t.c)

    def assertColumnType(self, engine, table, column, sqltype):
        t = utils.get_table(engine, table)
        col = getattr(t.c, column)
        self.assertIsInstance(col.type, sqltype)

    def assertColumnNotExists(self, engine, table, column):
        t = utils.get_table(engine, table)
        self.assertNotIn(column, t.c)

    def assertColumnIsNullable(self, engine, table, column):
        t = utils.get_table(engine, table)
        col = getattr(t.c, column)
        self.assertTrue(col.nullable)

    def assertColumnIsNotNullable(self, engine, table, column_name):
        table = utils.get_table(engine, table)
        column = getattr(table.c, column_name)
        self.assertFalse(column.nullable)

    def assertIndexExists(self, engine, table, index):
        t = utils.get_table(engine, table)
        index_names = [idx.name for idx in t.indexes]
        self.assertIn(index, index_names)

    def assertIndexMembers(self, engine, table, index, members):
        self.assertIndexExists(engine, table, index)

        t = utils.get_table(engine, table)
        index_columns = []
        for idx in t.indexes:
            if idx.name == index:
                for ix in idx.columns:
                    index_columns.append(ix.name)
                break

        self.assertEqual(sorted(members), sorted(index_columns))

    def _pre_upgrade_031(self, engine):
        raw_template = utils.get_table(engine, 'raw_template')
        templ = []
        for i in range(300, 303, 1):
            t = dict(id=i, template='{}', files='{}')
            engine.execute(raw_template.insert(), [t])
            templ.append(t)

        user_creds = utils.get_table(engine, 'user_creds')
        user = [dict(id=4, username='angus', password='notthis',
                     tenant='mine', auth_url='bla',
                     tenant_id=str(uuid.uuid4()),
                     trust_id='',
                     trustor_user_id='')]
        engine.execute(user_creds.insert(), user)

        stack = utils.get_table(engine, 'stack')
        stack_ids = [('967aaefb-152e-405d-b13a-35d4c816390c', 0),
                     ('9e9deba9-a303-4f29-84d3-c8165647c47e', 1),
                     ('9a4bd1ec-8b21-46cd-964a-f66cb1cfa2f9', 2)]
        data = [dict(id=ll_id, name='fruity',
                     raw_template_id=templ[templ_id]['id'],
                     user_creds_id=user[0]['id'],
                     username='angus', disable_rollback=True)
                for ll_id, templ_id in stack_ids]

        engine.execute(stack.insert(), data)
        return data

    def _check_031(self, engine, data):
        self.assertColumnExists(engine, 'stack_lock', 'stack_id')
        self.assertColumnExists(engine, 'stack_lock', 'engine_id')
        self.assertColumnExists(engine, 'stack_lock', 'created_at')
        self.assertColumnExists(engine, 'stack_lock', 'updated_at')

    def _check_034(self, engine, data):
        self.assertColumnExists(engine, 'raw_template', 'files')

    def _pre_upgrade_035(self, engine):
        # The stacks id are for the 33 version migration
        event_table = utils.get_table(engine, 'event')
        data = [{
            'id': '22222222-152e-405d-b13a-35d4c816390c',
            'stack_id': '967aaefb-152e-405d-b13a-35d4c816390c',
            'resource_action': 'Test',
            'resource_status': 'TEST IN PROGRESS',
            'resource_name': 'Testing Resource',
            'physical_resource_id': '3465d1ec-8b21-46cd-9dgf-f66cttrh53f9',
            'resource_status_reason': '',
            'resource_type': '',
            'resource_properties': None,
            'created_at': timeutils.utcnow()},
            {'id': '11111111-152e-405d-b13a-35d4c816390c',
             'stack_id': '967aaefb-152e-405d-b13a-35d4c816390c',
             'resource_action': 'Test',
             'resource_status': 'TEST COMPLETE',
             'resource_name': 'Testing Resource',
             'physical_resource_id': '3465d1ec-8b21-46cd-9dgf-f66cttrh53f9',
             'resource_status_reason': '',
             'resource_type': '',
             'resource_properties': None,
             'created_at': timeutils.utcnow() +
                datetime.timedelta(days=5)}]
        engine.execute(event_table.insert(), data)
        return data

    def _check_035(self, engine, data):
        self.assertColumnExists(engine, 'event', 'id')
        self.assertColumnExists(engine, 'event', 'uuid')

        event_table = utils.get_table(engine, 'event')
        events_in_db = list(event_table.select().execute())
        last_id = 0
        for index, event in enumerate(data):
            last_id = index + 1
            self.assertEqual(last_id, events_in_db[index].id)
            self.assertEqual(event['id'], events_in_db[index].uuid)

        # Check that the autoincremental id is ok
        data = [{
            'uuid': '33333333-152e-405d-b13a-35d4c816390c',
            'stack_id': '967aaefb-152e-405d-b13a-35d4c816390c',
            'resource_action': 'Test',
            'resource_status': 'TEST COMPLEATE AGAIN',
            'resource_name': 'Testing Resource',
            'physical_resource_id': '3465d1ec-8b21-46cd-9dgf-f66cttrh53f9',
            'resource_status_reason': '',
            'resource_type': '',
            'resource_properties': None,
            'created_at': timeutils.utcnow()}]
        result = engine.execute(event_table.insert(), data)
        self.assertEqual(last_id + 1, result.inserted_primary_key[0])

    def _check_036(self, engine, data):
        self.assertColumnExists(engine, 'stack', 'stack_user_project_id')

    def _pre_upgrade_037(self, engine):
        raw_template = utils.get_table(engine, 'raw_template')
        templ = '''{"heat_template_version": "2013-05-23",
        "parameters": {
           "key_name": {
              "Type": "string"
           }
          }
        }'''
        data = [dict(id=4, template=templ, files='{}')]
        engine.execute(raw_template.insert(), data)
        return data[0]

    def _check_037(self, engine, data):
        raw_template = utils.get_table(engine, 'raw_template')
        templs = list(raw_template.select().
                      where(raw_template.c.id == str(data['id'])).
                      execute())
        template = jsonutils.loads(templs[0].template)
        data_template = jsonutils.loads(data['template'])
        self.assertNotIn('Type', template['parameters']['key_name'])
        self.assertIn('type', template['parameters']['key_name'])
        self.assertEqual(template['parameters']['key_name']['type'],
                         data_template['parameters']['key_name']['Type'])

    def _check_038(self, engine, data):
        self.assertColumnNotExists(engine, 'software_config', 'io')

    def _check_039(self, engine, data):
        self.assertColumnIsNullable(engine, 'stack', 'user_creds_id')

    def _check_040(self, engine, data):
        self.assertColumnNotExists(engine, 'software_deployment', 'signal_id')

    def _pre_upgrade_041(self, engine):
        raw_template = utils.get_table(engine, 'raw_template')
        templ = '''{"heat_template_version": "2013-05-23",
        "resources": {
            "my_instance": {
                "Type": "OS::Nova::Server"
            }
          },
        "outputs": {
            "instance_ip": {
                "Value": { "get_attr": "[my_instance, networks]" }
            }
          }
        }'''
        data = [dict(id=7, template=templ, files='{}')]
        engine.execute(raw_template.insert(), data)
        return data[0]

    def _check_041(self, engine, data):
        raw_template = utils.get_table(engine, 'raw_template')
        templs = list(raw_template.select().
                      where(raw_template.c.id == str(data['id'])).
                      execute())
        template = jsonutils.loads(templs[0].template)
        self.assertIn('type', template['resources']['my_instance'])
        self.assertNotIn('Type', template['resources']['my_instance'])
        self.assertIn('value', template['outputs']['instance_ip'])
        self.assertNotIn('Value', template['outputs']['instance_ip'])

    def _pre_upgrade_043(self, engine):
        raw_template = utils.get_table(engine, 'raw_template')
        templ = '''{"HeatTemplateFormatVersion" : "2012-12-11",
        "Parameters" : {
          "foo" : { "Type" : "String", "NoEcho": "True" },
          "bar" : { "Type" : "String", "NoEcho": "True", "Default": "abc" },
          "blarg" : { "Type" : "String", "Default": "quux" }
          }
        }'''
        data = [dict(id=8, template=templ, files='{}')]
        engine.execute(raw_template.insert(), data)
        return data[0]

    def _check_043(self, engine, data):
        raw_template = utils.get_table(engine, 'raw_template')
        templ = list(raw_template.select().
                     where(raw_template.c.id == data['id']).execute())
        template = jsonutils.loads(templ[0].template)
        self.assertEqual(template['HeatTemplateFormatVersion'], '2012-12-12')

    def _pre_upgrade_045(self, engine):
        raw_template = utils.get_table(engine, 'raw_template')
        templ = []
        for i in range(200, 203, 1):
            t = dict(id=i, template='{}', files='{}')
            engine.execute(raw_template.insert(), [t])
            templ.append(t)

        user_creds = utils.get_table(engine, 'user_creds')
        user = [dict(id=6, username='steve', password='notthis',
                     tenant='mine', auth_url='bla',
                     tenant_id=str(uuid.uuid4()),
                     trust_id='',
                     trustor_user_id='')]
        engine.execute(user_creds.insert(), user)

        stack = utils.get_table(engine, 'stack')
        stack_ids = [('s1', '967aaefb-152e-505d-b13a-35d4c816390c', 0),
                     ('s2', '9e9deba9-a303-5f29-84d3-c8165647c47e', 1),
                     ('s1*', '9a4bd1ec-8b21-56cd-964a-f66cb1cfa2f9', 2)]
        data = [dict(id=ll_id, name=name,
                     raw_template_id=templ[templ_id]['id'],
                     user_creds_id=user[0]['id'],
                     username='steve', disable_rollback=True)
                for name, ll_id, templ_id in stack_ids]
        data[2]['owner_id'] = '967aaefb-152e-505d-b13a-35d4c816390c'

        engine.execute(stack.insert(), data)
        return data

    def _check_045(self, engine, data):
        self.assertColumnExists(engine, 'stack', 'backup')
        stack_table = utils.get_table(engine, 'stack')
        stacks_in_db = list(stack_table.select().execute())
        stack_names_in_db = [s.name for s in stacks_in_db]
        # Assert the expected stacks are still there
        for stack in data:
            self.assertIn(stack['name'], stack_names_in_db)
        # And that the backup flag is set as expected
        for stack in stacks_in_db:
            if stack.name.endswith('*'):
                self.assertTrue(stack.backup)
            else:
                self.assertFalse(stack.backup)

    def _check_046(self, engine, data):
        self.assertColumnExists(engine, 'resource', 'properties_data')

    def _pre_upgrade_047(self, engine):
        raw_template = utils.get_table(engine, 'raw_template')
        templ = []
        for i in range(100, 105, 1):
            t = dict(id=i, template='{}', files='{}')
            engine.execute(raw_template.insert(), [t])
            templ.append(t)

        user_creds = utils.get_table(engine, 'user_creds')
        user = [dict(id=7, username='steve', password='notthis',
                     tenant='mine', auth_url='bla',
                     tenant_id=str(uuid.uuid4()),
                     trust_id='',
                     trustor_user_id='')]
        engine.execute(user_creds.insert(), user)

        stack = utils.get_table(engine, 'stack')
        stack_ids = [
            ('s9', '167aaefb-152e-505d-b13a-35d4c816390c', 0),
            ('n1', '1e9deba9-a303-5f29-84d3-c8165647c47e', 1),
            ('n2', '1e9deba9-a304-5f29-84d3-c8165647c47e', 2),
            ('n3', '1e9deba9-a305-5f29-84d3-c8165647c47e', 3),
            ('s9*', '1a4bd1ec-8b21-56cd-964a-f66cb1cfa2f9', 4)]
        data = [dict(id=ll_id, name=name,
                     raw_template_id=templ[tmpl_id]['id'],
                     user_creds_id=user[0]['id'],
                     owner_id=None,
                     backup=False,
                     username='steve', disable_rollback=True)
                for name, ll_id, tmpl_id in stack_ids]
        # Make a nested tree s1->s2->s3->s4 with a s1 backup
        data[1]['owner_id'] = '167aaefb-152e-505d-b13a-35d4c816390c'
        data[2]['owner_id'] = '1e9deba9-a303-5f29-84d3-c8165647c47e'
        data[3]['owner_id'] = '1e9deba9-a304-5f29-84d3-c8165647c47e'
        data[4]['owner_id'] = '167aaefb-152e-505d-b13a-35d4c816390c'
        data[4]['backup'] = True
        engine.execute(stack.insert(), data)
        return data

    def _check_047(self, engine, data):
        self.assertColumnExists(engine, 'stack', 'nested_depth')
        stack_table = utils.get_table(engine, 'stack')
        stacks_in_db = list(stack_table.select().execute())
        stack_ids_in_db = [s.id for s in stacks_in_db]

        # Assert the expected stacks are still there
        for stack in data:
            self.assertIn(stack['id'], stack_ids_in_db)

        # And that the depth is set as expected
        def n_depth(sid):
            s = [s for s in stacks_in_db if s.id == sid][0]
            return s.nested_depth

        self.assertEqual(0, n_depth('167aaefb-152e-505d-b13a-35d4c816390c'))
        self.assertEqual(1, n_depth('1e9deba9-a303-5f29-84d3-c8165647c47e'))
        self.assertEqual(2, n_depth('1e9deba9-a304-5f29-84d3-c8165647c47e'))
        self.assertEqual(3, n_depth('1e9deba9-a305-5f29-84d3-c8165647c47e'))
        self.assertEqual(0, n_depth('1a4bd1ec-8b21-56cd-964a-f66cb1cfa2f9'))

    def _check_049(self, engine, data):
        self.assertColumnExists(engine, 'user_creds', 'region_name')

    def _check_051(self, engine, data):
        column_list = [('id', False),
                       ('host', False),
                       ('topic', False),
                       ('binary', False),
                       ('hostname', False),
                       ('engine_id', False),
                       ('report_interval', False),
                       ('updated_at', True),
                       ('created_at', True),
                       ('deleted_at', True)]
        for column in column_list:
            self.assertColumnExists(engine, 'service', column[0])
            if not column[1]:
                self.assertColumnIsNotNullable(engine, 'service', column[0])
            else:
                self.assertColumnIsNullable(engine, 'service', column[0])

    def _check_052(self, engine, data):
        self.assertColumnExists(engine, 'stack', 'convergence')

    def _check_055(self, engine, data):
        self.assertColumnExists(engine, 'stack', 'prev_raw_template_id')
        self.assertColumnExists(engine, 'stack', 'current_traversal')
        self.assertColumnExists(engine, 'stack', 'current_deps')

    def _pre_upgrade_056(self, engine):
        raw_template = utils.get_table(engine, 'raw_template')
        templ = []
        for i in range(900, 903, 1):
            t = dict(id=i, template='{}', files='{}')
            engine.execute(raw_template.insert(), [t])
            templ.append(t)

        user_creds = utils.get_table(engine, 'user_creds')
        user = [dict(id=uid, username='test_user', password='password',
                     tenant='test_project', auth_url='bla',
                     tenant_id=str(uuid.uuid4()),
                     trust_id='',
                     trustor_user_id='') for uid in range(900, 903)]
        engine.execute(user_creds.insert(), user)

        stack = utils.get_table(engine, 'stack')
        stack_ids = [('967aaefa-152e-405d-b13a-35d4c816390c', 0),
                     ('9e9debab-a303-4f29-84d3-c8165647c47e', 1),
                     ('9a4bd1e9-8b21-46cd-964a-f66cb1cfa2f9', 2)]
        data = [dict(id=ll_id, name=ll_id,
                     raw_template_id=templ[templ_id]['id'],
                     user_creds_id=user[templ_id]['id'],
                     username='test_user',
                     disable_rollback=True,
                     parameters='test_params',
                     created_at=timeutils.utcnow(),
                     deleted_at=None)
                for ll_id, templ_id in stack_ids]
        data[-1]['deleted_at'] = timeutils.utcnow()

        engine.execute(stack.insert(), data)
        return data

    def _check_056(self, engine, data):
        self.assertColumnNotExists(engine, 'stack', 'parameters')

        self.assertColumnExists(engine, 'raw_template', 'environment')
        self.assertColumnExists(engine, 'raw_template', 'predecessor')

        # Get the parameters in stack table
        stack_parameters = {}
        for stack in data:
            templ_id = stack['raw_template_id']
            stack_parameters[templ_id] = (stack['parameters'],
                                          stack.get('deleted_at'))

        # validate whether its moved to raw_template
        raw_template_table = utils.get_table(engine, 'raw_template')
        raw_templates = raw_template_table.select().execute()

        for raw_template in raw_templates:
            if raw_template.id in stack_parameters:
                stack_param, deleted_at = stack_parameters[raw_template.id]
                tmpl_env = raw_template.environment
                if engine.name == 'sqlite' and deleted_at is None:
                    stack_param = '"%s"' % stack_param
                if deleted_at is None:
                    self.assertEqual(stack_param,
                                     tmpl_env,
                                     'parameters migration from stack to '
                                     'raw_template failed')
                else:
                    self.assertIsNone(tmpl_env,
                                      'parameters migration did not skip '
                                      'deleted stack')

    def _pre_upgrade_057(self, engine):
        # template
        raw_template = utils.get_table(engine, 'raw_template')
        templ = [dict(id=11, template='{}', files='{}')]
        engine.execute(raw_template.insert(), templ)

        # credentials
        user_creds = utils.get_table(engine, 'user_creds')
        user = [dict(id=11, username='steve', password='notthis',
                     tenant='mine', auth_url='bla',
                     tenant_id=str(uuid.uuid4()),
                     trust_id='',
                     trustor_user_id='')]
        engine.execute(user_creds.insert(), user)

        # stack
        stack = utils.get_table(engine, 'stack')
        stack_data = [dict(id='867aaefb-152e-505d-b13a-35d4c816390c',
                           name='s1',
                           raw_template_id=templ[0]['id'],
                           user_creds_id=user[0]['id'],
                           username='steve', disable_rollback=True)]
        engine.execute(stack.insert(), stack_data)

        # resource
        resource = utils.get_table(engine, 'resource')
        res_data = [dict(id='167aaefb-152e-505d-b13a-35d4c816390c',
                         name='res-4',
                         stack_id=stack_data[0]['id'],
                         user_creds_id=user[0]['id']),
                    dict(id='177aaefb-152e-505d-b13a-35d4c816390c',
                         name='res-5',
                         stack_id=stack_data[0]['id'],
                         user_creds_id=user[0]['id'])]
        engine.execute(resource.insert(), res_data)

        # resource_data
        resource_data = utils.get_table(engine, 'resource_data')
        rd_data = [dict(key='fruit',
                        value='blueberries',
                        reduct=False,
                        resource_id=res_data[0]['id']),
                   dict(key='fruit',
                        value='apples',
                        reduct=False,
                        resource_id=res_data[1]['id'])]
        engine.execute(resource_data.insert(), rd_data)

        return {'resource': res_data, 'resource_data': rd_data}

    def _check_057(self, engine, data):
        def uuid_in_res_data(res_uuid):
            for rd in data['resource']:
                if rd['id'] == res_uuid:
                    return True
            return False

        def rd_matches_old_data(key, value, res_uuid):
            for rd in data['resource_data']:
                if (rd['resource_id'] == res_uuid and rd['key'] == key
                        and rd['value'] == value):
                    return True
            return False

        self.assertColumnIsNotNullable(engine, 'resource', 'id')
        res_table = utils.get_table(engine, 'resource')
        res_in_db = list(res_table.select().execute())
        # confirm the resource.id is an int and the uuid field has been
        # copied from the old id.
        for r in res_in_db:
            self.assertIsInstance(r.id, six.integer_types)
            self.assertTrue(uuid_in_res_data(r.uuid))

        # confirm that the new resource_id points to the correct resource.
        rd_table = utils.get_table(engine, 'resource_data')
        rd_in_db = list(rd_table.select().execute())
        for rd in rd_in_db:
            for r in res_in_db:
                if rd.resource_id == r.id:
                    self.assertTrue(rd_matches_old_data(rd.key, rd.value,
                                                        r.uuid))

    def _check_058(self, engine, data):
        self.assertColumnExists(engine, 'resource', 'engine_id')
        self.assertColumnExists(engine, 'resource', 'atomic_key')

    def _check_059(self, engine, data):
        column_list = [('entity_id', False),
                       ('traversal_id', False),
                       ('is_update', False),
                       ('atomic_key', False),
                       ('stack_id', False),
                       ('input_data', True),
                       ('updated_at', True),
                       ('created_at', True)]
        for column in column_list:
            self.assertColumnExists(engine, 'sync_point', column[0])
            if not column[1]:
                self.assertColumnIsNotNullable(engine, 'sync_point',
                                               column[0])
            else:
                self.assertColumnIsNullable(engine, 'sync_point', column[0])

    def _check_060(self, engine, data):
        column_list = ['needed_by', 'requires', 'replaces', 'replaced_by',
                       'current_template_id']
        for column in column_list:
            self.assertColumnExists(engine, 'resource', column)

    def _check_061(self, engine, data):
        for tab_name in ['stack', 'resource', 'software_deployment']:
            self.assertColumnType(engine, tab_name, 'status_reason',
                                  sqlalchemy.Text)

    def _check_062(self, engine, data):
        self.assertColumnExists(engine, 'stack', 'parent_resource_name')

    def _check_063(self, engine, data):
        self.assertColumnExists(engine, 'resource',
                                'properties_data_encrypted')

    def _check_064(self, engine, data):
        self.assertColumnNotExists(engine, 'raw_template',
                                   'predecessor')

    def _check_065(self, engine, data):
        self.assertColumnExists(engine, 'resource', 'root_stack_id')
        self.assertIndexExists(engine, 'resource', 'ix_resource_root_stack_id')

    def _check_071(self, engine, data):
        self.assertIndexExists(engine, 'stack', 'ix_stack_owner_id')
        self.assertIndexMembers(engine, 'stack', 'ix_stack_owner_id',
                                ['owner_id'])

    def _check_073(self, engine, data):
        # check if column still exists and is not nullable.
        self.assertColumnIsNotNullable(engine, 'resource_data', 'resource_id')
        # Ensure that only one foreign key exists and is created as expected.
        inspector = sqlalchemy.engine.reflection.Inspector.from_engine(engine)
        resource_data_fkeys = inspector.get_foreign_keys('resource_data')
        self.assertEqual(1, len(resource_data_fkeys))
        fk = resource_data_fkeys[0]
        self.assertEqual('fk_resource_id', fk['name'])
        self.assertEqual(['resource_id'], fk['constrained_columns'])
        self.assertEqual('resource', fk['referred_table'])
        self.assertEqual(['id'], fk['referred_columns'])

    def _check_079(self, engine, data):
        self.assertColumnExists(engine, 'resource',
                                'rsrc_prop_data_id')
        self.assertColumnExists(engine, 'event',
                                'rsrc_prop_data_id')
        column_list = [('id', False),
                       ('data', True),
                       ('encrypted', True),
                       ('updated_at', True),
                       ('created_at', True)]

        for column in column_list:
            self.assertColumnExists(engine,
                                    'resource_properties_data', column[0])
            if not column[1]:
                self.assertColumnIsNotNullable(engine,
                                               'resource_properties_data',
                                               column[0])
            else:
                self.assertColumnIsNullable(engine,
                                            'resource_properties_data',
                                            column[0])

    def _check_080(self, engine, data):
        self.assertColumnExists(engine, 'resource',
                                'attr_data_id')


class DbTestCase(test_fixtures.OpportunisticDBTestMixin,
                 test_base.BaseTestCase):
    def setUp(self):
        super(DbTestCase, self).setUp()

        self.engine = enginefacade.writer.get_engine()
        self.sessionmaker = enginefacade.writer.get_sessionmaker()


class TestHeatMigrationsMySQL(DbTestCase, HeatMigrationsCheckers):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class TestHeatMigrationsPostgreSQL(DbTestCase, HeatMigrationsCheckers):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture


class TestHeatMigrationsSQLite(DbTestCase, HeatMigrationsCheckers):
    pass


class ModelsMigrationSyncMixin(object):

    def get_metadata(self):
        return models.BASE.metadata

    def get_engine(self):
        return self.engine

    def db_sync(self, engine):
        migration.db_sync(engine=engine)

    def include_object(self, object_, name, type_, reflected, compare_to):
        if name in ['migrate_version'] and type_ == 'table':
            return False
        return True


class ModelsMigrationsSyncMysql(DbTestCase,
                                ModelsMigrationSyncMixin,
                                test_migrations.ModelsMigrationsSync):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class ModelsMigrationsSyncPostgres(DbTestCase,
                                   ModelsMigrationSyncMixin,
                                   test_migrations.ModelsMigrationsSync):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture


class ModelsMigrationsSyncSQLite(DbTestCase,
                                 ModelsMigrationSyncMixin,
                                 test_migrations.ModelsMigrationsSync):
    pass
