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

from heat.db.sqlalchemy import utils as migrate_utils
from heat.tests import common
from heat.tests import utils

from sqlalchemy.schema import (Column, MetaData, Table)
from sqlalchemy.types import (Boolean, String, Integer)
from sqlalchemy import (CheckConstraint, UniqueConstraint,
                        ForeignKey, ForeignKeyConstraint)


def _has_constraint(cset, ctype, cname):
    for c in cset:
        if (isinstance(c, ctype)
                and c.name == cname):
            return True
    else:
            return False


class DBMigrationUtilsTest(common.HeatTestCase):

    def setUp(self):
        super(DBMigrationUtilsTest, self).setUp()
        self.engine = utils.get_engine()

    def test_clone_table_adds_or_deletes_columns(self):
        meta = MetaData()
        meta.bind = self.engine

        table = Table('dummy',
                      meta,
                      Column('id', String(36), primary_key=True,
                             nullable=False),
                      Column('A', Boolean, default=False)
                      )
        table.create()

        newcols = [
            Column('B', Boolean, default=False),
            Column('C', String(255), default='foobar')
        ]
        ignorecols = [
            table.c.A.name
        ]
        new_table = migrate_utils.clone_table('new_dummy', table, meta,
                                              newcols=newcols,
                                              ignorecols=ignorecols)

        col_names = [c.name for c in new_table.columns]

        self.assertEqual(3, len(col_names))
        self.assertIsNotNone(new_table.c.B)
        self.assertIsNotNone(new_table.c.C)
        self.assertNotIn('A', col_names)

    def test_clone_table_swaps_columns(self):
        meta = MetaData()
        meta.bind = self.engine

        table = Table("dummy1",
                      meta,
                      Column('id', String(36), primary_key=True,
                             nullable=False),
                      Column('A', Boolean, default=False),
                      )
        table.create()

        swapcols = {
            'A': Column('A', Integer, default=1),
        }

        new_table = migrate_utils.clone_table('swap_dummy', table, meta,
                                              swapcols=swapcols)

        self.assertIsNotNone(new_table.c.A)
        self.assertEqual(Integer, type(new_table.c.A.type))

    def test_clone_table_retains_constraints(self):
        meta = MetaData()
        meta.bind = self.engine
        parent = Table('parent',
                       meta,
                       Column('id', String(36), primary_key=True,
                              nullable=False),
                       Column('A', Integer),
                       Column('B', Integer),
                       Column('C', Integer,
                              CheckConstraint('C>100', name="above 100")),
                       Column('D', Integer, unique=True),

                       UniqueConstraint('A', 'B', name='uix_1')
                       )
        parent.create()

        child = Table('child',
                      meta,
                      Column('id', String(36),
                             ForeignKey('parent.id', name="parent_ref"),
                             primary_key=True,
                             nullable=False),
                      Column('A', Boolean, default=False)
                      )
        child.create()

        ignorecols = [
            parent.c.D.name,
        ]

        new_parent = migrate_utils.clone_table('new_parent', parent, meta,
                                               ignorecols=ignorecols)
        new_child = migrate_utils.clone_table('new_child', child, meta)

        self.assertTrue(_has_constraint(new_parent.constraints,
                                        UniqueConstraint, 'uix_1'))
        self.assertTrue(_has_constraint(new_parent.c.C.constraints,
                                        CheckConstraint, 'above 100'))
        self.assertTrue(_has_constraint(new_child.constraints,
                                        ForeignKeyConstraint, 'parent_ref'))

    def test_clone_table_ignores_constraints(self):
        meta = MetaData()
        meta.bind = self.engine
        table = Table('constraints_check',
                      meta,
                      Column('id', String(36), primary_key=True,
                             nullable=False),
                      Column('A', Integer),
                      Column('B', Integer),
                      Column('C', Integer,
                             CheckConstraint('C>100', name="above 100")),

                      UniqueConstraint('A', 'B', name='uix_1')
                      )
        table.create()

        ignorecons = [
            'uix_1',
        ]

        new_table = migrate_utils.clone_table('constraints_check_tmp', table,
                                              meta, ignorecons=ignorecons)
        self.assertFalse(_has_constraint(new_table.constraints,
                                         UniqueConstraint, 'uix_1'))

    def test_migrate_data(self):
        meta = MetaData(bind=self.engine)

        # create TableA
        table_a = Table('TableA',
                        meta,
                        Column('id', Integer, primary_key=True),
                        Column('first', String(8), nullable=False),
                        Column('second', Integer))
        table_a.create()

        # update it with sample data
        values = [
            {'id': 1, 'first': 'a'},
            {'id': 2, 'first': 'b'},
            {'id': 3, 'first': 'c'}
        ]

        for value in values:
            self.engine.execute(table_a.insert(values=value))

        # create TableB similar to TableA, except column 'second'
        table_b = Table('TableB',
                        meta,
                        Column('id', Integer, primary_key=True),
                        Column('first', String(8), nullable=False))
        table_b.create()

        # migrate data
        migrate_utils.migrate_data(self.engine,
                                   table_a,
                                   table_b,
                                   ['second'])

        # validate table_a is dropped
        self.assertTrue(self.engine.dialect.has_table(
            self.engine.connect(),
            'TableA'),
            'Data migration failed to drop source table')

        # validate table_b is updated with data from table_a
        table_b_rows = list(table_b.select().execute())
        self.assertEqual(3,
                         len(table_b_rows),
                         "Data migration is failed")
        table_b_values = []
        for row in table_b_rows:
            table_b_values.append({'id': row.id,
                                   'first': row.first})

        self.assertEqual(values,
                         table_b_values,
                         "Data migration failed with invalid data copy")
