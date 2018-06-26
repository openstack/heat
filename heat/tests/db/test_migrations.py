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

import fixtures
import os

from migrate.versioning import repository
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils
from oslotest import base as test_base
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
