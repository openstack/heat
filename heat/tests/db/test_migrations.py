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
import shutil
import subprocess
import tempfile
import uuid

from migrate.versioning import repository
import sqlalchemy

from heat.db.sqlalchemy import migrate_repo
from heat.db.sqlalchemy import migration
from heat.openstack.common.db.sqlalchemy import test_migrations
from heat.openstack.common import log as logging
from heat.openstack.common.py3kcompat import urlutils


LOG = logging.getLogger(__name__)


def get_table(engine, name):
    """Returns an sqlalchemy table dynamically from db.

    Needed because the models don't work for us in migrations
    as models will be far out of sync with the current data.
    """
    metadata = sqlalchemy.MetaData()
    metadata.bind = engine
    return sqlalchemy.Table(name, metadata, autoload=True)


class TestHeatMigrations(test_migrations.BaseMigrationTestCase,
                         test_migrations.WalkVersionsMixin):
    """Test sqlalchemy-migrate migrations."""

    def __init__(self, *args, **kwargs):
        super(TestHeatMigrations, self).__init__(*args, **kwargs)

        self.DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(__file__),
                                                'test_migrations.conf')
        # Test machines can set the TEST_MIGRATIONS_CONF variable
        # to override the location of the config file for migration testing
        self.CONFIG_FILE_PATH = os.environ.get('TEST_MIGRATIONS_CONF',
                                               self.DEFAULT_CONFIG_FILE)
        self.MIGRATE_FILE = migrate_repo.__file__
        self.REPOSITORY = repository.Repository(
            os.path.abspath(os.path.dirname(self.MIGRATE_FILE)))

    def setUp(self):
        lock_dir = tempfile.mkdtemp()
        os.environ["HEAT_LOCK_PATH"] = lock_dir

        super(TestHeatMigrations, self).setUp()

        def clean_lock_dir():
            shutil.rmtree(lock_dir, ignore_errors=True)

        self.addCleanup(clean_lock_dir)
        self.snake_walk = False
        self.downgrade = False
        self.INIT_VERSION = migration.INIT_VERSION
        if self.migration_api is None:
            temp = __import__('heat.openstack.common.db.sqlalchemy.migration',
                              globals(), locals(),
                              ['versioning_api'], -1)
            self.migration_api = temp.versioning_api

    def test_walk_versions(self):
        for key, engine in self.engines.items():
            self._walk_versions(engine, self.snake_walk, self.downgrade)

    def assertColumnExists(self, engine, table, column):
        t = get_table(engine, table)
        self.assertIn(column, t.c)

    def assertColumnNotExists(self, engine, table, column):
        t = get_table(engine, table)
        self.assertNotIn(column, t.c)

    def assertColumnIsNullable(self, engine, table, column):
        t = get_table(engine, table)
        col = getattr(t.c, column)
        self.assertTrue(col.nullable)

    def assertIndexExists(self, engine, table, index):
        t = get_table(engine, table)
        index_names = [idx.name for idx in t.indexes]
        self.assertIn(index, index_names)

    def assertIndexMembers(self, engine, table, index, members):
        self.assertIndexExists(engine, table, index)

        t = get_table(engine, table)
        index_columns = None
        for idx in t.indexes:
            if idx.name == index:
                index_columns = idx.columns.keys()
                break

        self.assertEqual(sorted(members), sorted(index_columns))

    def _load_mysql_dump_file(self, engine, file_name):
        for key, eng in self.engines.items():
            if eng is engine:
                conn_string = self.test_databases[key]
                conn_pieces = urlutils.urlparse(conn_string)
                if conn_string.startswith('mysql'):
                    break
                else:
                    return

        (user, password, database, host) = \
            test_migrations.get_db_connection_info(conn_pieces)
        cmd = ('mysql -u \"%(user)s\" -p\"%(password)s\" -h %(host)s %(db)s '
               ) % {'user': user, 'password': password,
                    'host': host, 'db': database}
        file_path = os.path.join(os.path.dirname(__file__),
                                 file_name)
        with open(file_path) as sql_file:
            process = subprocess.Popen(cmd, shell=True,
                                       stdout=subprocess.PIPE,
                                       stdin=sql_file,
                                       stderr=subprocess.STDOUT)
            output = process.communicate()[0]
            self.assertEqual(0, process.returncode,
                             "Failed to run: %s\n%s" % (cmd, output))

    def _pre_upgrade_031(self, engine):
        raw_template = get_table(engine, 'raw_template')
        templ = [dict(id=3, template='{}')]
        engine.execute(raw_template.insert(), templ)

        user_creds = get_table(engine, 'user_creds')
        user = [dict(id=4, username='angus', password='notthis',
                     tenant='mine', auth_url='bla',
                     tenant_id=str(uuid.uuid4()),
                     trust_id='',
                     trustor_user_id='')]
        engine.execute(user_creds.insert(), user)

        stack = get_table(engine, 'stack')
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
        #The stacks id are for the 33 version migration
        event_table = get_table(engine, 'event')
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

        event_table = get_table(engine, 'event')
        events_in_db = list(event_table.select().execute())
        last_id = 0
        for index, event in enumerate(data):
            last_id = index + 1
            self.assertEqual(last_id, events_in_db[index].id)
            self.assertEqual(event['id'], events_in_db[index].uuid)

        #Check that the autoincremental id is ok
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

    def _check_038(self, engine, data):
        self.assertColumnNotExists(engine, 'software_config', 'io')

    def _check_039(self, engine, data):
        self.assertColumnIsNullable(engine, 'stack', 'user_creds_id')

    def _check_040(self, engine, data):
        self.assertColumnNotExists(engine, 'software_deployment', 'signal_id')
