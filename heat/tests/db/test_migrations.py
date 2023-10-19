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

"""Tests for database migrations."""

from alembic import command as alembic_api
from alembic import script as alembic_script
import fixtures
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslotest import base as test_base
import sqlalchemy
import testtools

from heat.db import migration
from heat.db import models


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
        table = sqlalchemy.Table("foo", sqlalchemy.MetaData())
        with BannedDBSchemaOperations(['Table']):
            self.assertRaises(DBNotAllowed, table.drop)
            self.assertRaises(DBNotAllowed, table.alter)


class HeatModelsMigrationsSync(test_migrations.ModelsMigrationsSync):

    def setUp(self):
        super().setUp()

        self.engine = enginefacade.writer.get_engine()
        self.sessionmaker = enginefacade.writer.get_sessionmaker()

    def get_metadata(self):
        return models.BASE.metadata

    def get_engine(self):
        return self.engine

    def db_sync(self, engine):
        migration.db_sync(engine=engine)

    def include_object(self, object_, name, type_, reflected, compare_to):
        return True


class ModelsMigrationsSyncMysql(
    HeatModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class ModelsMigrationsSyncPostgres(
    HeatModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture


class ModelsMigrationsSyncSQLite(
    HeatModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    pass


class DatabaseSanityChecks(
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    def setUp(self):
        super().setUp()
        self.engine = enginefacade.writer.get_engine()
        # self.patch(api, 'get_engine', lambda: self.engine)
        self.config = migration._find_alembic_conf()
        self.init_version = migration.ALEMBIC_INIT_VERSION

    def test_single_base_revision(self):
        """Ensure we only have a single base revision.

        There's no good reason for us to have diverging history, so validate
        that only one base revision exists. This will prevent simple errors
        where people forget to specify the base revision. If this fail for your
        change, look for migrations that do not have a 'revises' line in them.
        """
        script = alembic_script.ScriptDirectory.from_config(self.config)
        self.assertEqual(1, len(script.get_bases()))

    def test_single_head_revision(self):
        """Ensure we only have a single head revision.

        There's no good reason for us to have diverging history, so validate
        that only one head revision exists. This will prevent merge conflicts
        adding additional head revision points. If this fail for your change,
        look for migrations with the same 'revises' line in them.
        """
        script = alembic_script.ScriptDirectory.from_config(self.config)
        self.assertEqual(1, len(script.get_heads()))


class MigrationsWalk(
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    # Migrations can take a long time, particularly on underpowered CI nodes.
    # Give them some breathing room.
    TIMEOUT_SCALING_FACTOR = 4

    def setUp(self):
        super().setUp()
        self.engine = enginefacade.writer.get_engine()
        # self.patch(api, 'get_engine', lambda: self.engine)
        self.config = migration._find_alembic_conf()
        self.init_version = migration.ALEMBIC_INIT_VERSION

    def _migrate_up(self, revision, connection):
        check_method = getattr(self, f'_check_{revision}', None)
        if revision != self.init_version:  # no tests for the initial revision
            self.assertIsNotNone(
                check_method,
                f"DB Migration {revision} doesn't have a test; add one"
            )

        pre_upgrade = getattr(self, f'_pre_upgrade_{revision}', None)
        if pre_upgrade:
            pre_upgrade(connection)

        alembic_api.upgrade(self.config, revision)

        if check_method:
            check_method(connection)

    def test_walk_versions(self):
        with self.engine.begin() as connection:
            self.config.attributes['connection'] = connection
            script = alembic_script.ScriptDirectory.from_config(self.config)
            revisions = list(script.walk_revisions())
            # Need revisions from older to newer so the walk works as intended
            revisions.reverse()
            for revision_script in revisions:
                self._migrate_up(revision_script.revision, connection)


class TestMigrationsWalkSQLite(
    MigrationsWalk,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    pass


class TestMigrationsWalkMySQL(
    MigrationsWalk,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class TestMigrationsWalkPostgreSQL(
    MigrationsWalk,
    test_fixtures.OpportunisticDBTestMixin,
    test_base.BaseTestCase,
):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture
