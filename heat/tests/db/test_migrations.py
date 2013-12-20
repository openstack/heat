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

import os
import shutil
import sqlalchemy
import tempfile

from migrate.versioning import repository

from heat.db.sqlalchemy import migrate_repo
from heat.openstack.common import log as logging
from heat.openstack.common.db.sqlalchemy import test_migrations


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
        if self.migration_api is None:
            temp = __import__('heat.db.sqlalchemy.migration',
                              globals(), locals(),
                              ['versioning_api'], -1)
            self.migration_api = temp.versioning_api
            self.INIT_VERSION = temp.INIT_VERSION

    def test_walk_versions(self):
        for key, engine in self.engines.items():
            self._walk_versions(engine, self.snake_walk, self.downgrade)

    def assertColumnExists(self, engine, table, column):
        t = get_table(engine, table)
        self.assertIn(column, t.c)

    def assertColumnNotExists(self, engine, table, column):
        t = get_table(engine, table)
        self.assertNotIn(column, t.c)

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
