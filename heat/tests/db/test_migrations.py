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
import os
import uuid

from migrate.versioning import repository
from oslo.db.sqlalchemy import test_base
from oslo.db.sqlalchemy import test_migrations
from oslo.db.sqlalchemy import utils
from oslo.serialization import jsonutils
import pkg_resources as pkg

from heat.db.sqlalchemy import migrate_repo
from heat.db.sqlalchemy import migration
from heat.db.sqlalchemy import models
from heat.tests import common


class HeatMigrationsCheckers(test_migrations.WalkVersionsMixin,
                             common.FakeLogMixin):
    """Test sqlalchemy-migrate migrations."""

    snake_walk = True
    downgrade = True

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
        temp = __import__('oslo.db.sqlalchemy.migration', globals(),
                          locals(), ['versioning_api'], -1)
        return temp.versioning_api

    @property
    def migrate_engine(self):
        return self.engine

    def test_walk_versions(self):
        # TODO(viktors): Refactor this method, when we will be totally sure,
        #                that Heat use oslo.db>=0.4.0
        try:
            pkg.require('oslo.db>=0.4.0')
            self._walk_versions(self.snake_walk, self.downgrade)
        except pkg.VersionConflict:
            self._walk_versions(self.engine, self.snake_walk, self.downgrade)

    def assertColumnExists(self, engine, table, column):
        t = utils.get_table(engine, table)
        self.assertIn(column, t.c)

    def assertColumnNotExists(self, engine, table, column):
        t = utils.get_table(engine, table)
        self.assertNotIn(column, t.c)

    def assertColumnIsNullable(self, engine, table, column):
        t = utils.get_table(engine, table)
        col = getattr(t.c, column)
        self.assertTrue(col.nullable)

    def assertIndexExists(self, engine, table, index):
        t = utils.get_table(engine, table)
        index_names = [idx.name for idx in t.indexes]
        self.assertIn(index, index_names)

    def assertIndexMembers(self, engine, table, index, members):
        self.assertIndexExists(engine, table, index)

        t = utils.get_table(engine, table)
        index_columns = None
        for idx in t.indexes:
            if idx.name == index:
                index_columns = idx.columns.keys()
                break

        self.assertEqual(sorted(members), sorted(index_columns))

    def _pre_upgrade_031(self, engine):
        raw_template = utils.get_table(engine, 'raw_template')
        templ = [dict(id=3, template='{}')]
        engine.execute(raw_template.insert(), templ)

        user_creds = utils.get_table(engine, 'user_creds')
        user = [dict(id=4, username='angus', password='notthis',
                     tenant='mine', auth_url='bla',
                     tenant_id=str(uuid.uuid4()),
                     trust_id='',
                     trustor_user_id='')]
        engine.execute(user_creds.insert(), user)

        stack = utils.get_table(engine, 'stack')
        stack_ids = ['967aaefb-152e-405d-b13a-35d4c816390c',
                     '9e9deba9-a303-4f29-84d3-c8165647c47e',
                     '9a4bd1ec-8b21-46cd-964a-f66cb1cfa2f9']
        data = [dict(id=ll_id, name='fruity',
                     raw_template_id=templ[0]['id'],
                     user_creds_id=user[0]['id'],
                     username='angus', disable_rollback=True)
                for ll_id in stack_ids]

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
            'created_at': datetime.datetime.now()},
            {'id': '11111111-152e-405d-b13a-35d4c816390c',
             'stack_id': '967aaefb-152e-405d-b13a-35d4c816390c',
             'resource_action': 'Test',
             'resource_status': 'TEST COMPLETE',
             'resource_name': 'Testing Resource',
             'physical_resource_id': '3465d1ec-8b21-46cd-9dgf-f66cttrh53f9',
             'resource_status_reason': '',
             'resource_type': '',
             'resource_properties': None,
             'created_at': datetime.datetime.now() +
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
            'created_at': datetime.datetime.now()}]
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
                "Value": { "get_attr": "[my_instance, first_address]" }
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
        templ = [dict(id=5, template='{}', files='{}')]
        engine.execute(raw_template.insert(), templ)

        user_creds = utils.get_table(engine, 'user_creds')
        user = [dict(id=6, username='steve', password='notthis',
                     tenant='mine', auth_url='bla',
                     tenant_id=str(uuid.uuid4()),
                     trust_id='',
                     trustor_user_id='')]
        engine.execute(user_creds.insert(), user)

        stack = utils.get_table(engine, 'stack')
        stack_ids = [('s1', '967aaefb-152e-505d-b13a-35d4c816390c'),
                     ('s2', '9e9deba9-a303-5f29-84d3-c8165647c47e'),
                     ('s1*', '9a4bd1ec-8b21-56cd-964a-f66cb1cfa2f9')]
        data = [dict(id=ll_id, name=name,
                     raw_template_id=templ[0]['id'],
                     user_creds_id=user[0]['id'],
                     username='steve', disable_rollback=True)
                for name, ll_id in stack_ids]
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
        templ = [dict(id=6, template='{}', files='{}')]
        engine.execute(raw_template.insert(), templ)

        user_creds = utils.get_table(engine, 'user_creds')
        user = [dict(id=7, username='steve', password='notthis',
                     tenant='mine', auth_url='bla',
                     tenant_id=str(uuid.uuid4()),
                     trust_id='',
                     trustor_user_id='')]
        engine.execute(user_creds.insert(), user)

        stack = utils.get_table(engine, 'stack')
        stack_ids = [('s9', '167aaefb-152e-505d-b13a-35d4c816390c'),
                     ('n1', '1e9deba9-a303-5f29-84d3-c8165647c47e'),
                     ('n2', '1e9deba9-a304-5f29-84d3-c8165647c47e'),
                     ('n3', '1e9deba9-a305-5f29-84d3-c8165647c47e'),
                     ('s9*', '1a4bd1ec-8b21-56cd-964a-f66cb1cfa2f9')]
        data = [dict(id=ll_id, name=name,
                     raw_template_id=templ[0]['id'],
                     user_creds_id=user[0]['id'],
                     owner_id=None,
                     backup=False,
                     username='steve', disable_rollback=True)
                for name, ll_id in stack_ids]
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


class TestHeatMigrationsMySQL(HeatMigrationsCheckers,
                              test_base.MySQLOpportunisticTestCase):
    pass


class TestHeatMigrationsPostgreSQL(HeatMigrationsCheckers,
                                   test_base.PostgreSQLOpportunisticTestCase):
    pass


class TestHeatMigrationsSQLite(HeatMigrationsCheckers,
                               test_base.DbTestCase):
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


class ModelsMigrationsSyncMysql(ModelsMigrationSyncMixin,
                                test_migrations.ModelsMigrationsSync,
                                test_base.MySQLOpportunisticTestCase):
    pass


class ModelsMigrationsSyncPostgres(ModelsMigrationSyncMixin,
                                   test_migrations.ModelsMigrationsSync,
                                   test_base.PostgreSQLOpportunisticTestCase):
    pass


class ModelsMigrationsSyncSQLite(ModelsMigrationSyncMixin,
                                 test_migrations.ModelsMigrationsSync,
                                 test_base.DbTestCase):
    pass
