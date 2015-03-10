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

import sqlalchemy

from heat.db.sqlalchemy import utils as migrate_utils


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    convergence = sqlalchemy.Column('convergence', sqlalchemy.Boolean,
                                    default=False)
    convergence.create(stack)


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    if migrate_engine.name == 'sqlite':
        _downgrade_052_sqlite(migrate_engine, meta, stack)
    else:
        stack.c.convergence.drop()


def _downgrade_052_sqlite(migrate_engine, metadata, table):

    table_name = table.name

    constraints = [
        c.copy() for c in table.constraints
        if not isinstance(c, sqlalchemy.CheckConstraint)
    ]
    columns = [c.copy() for c in table.columns if c.name != "convergence"]

    new_table = sqlalchemy.Table(table_name + "__tmp__", metadata,
                                 *(columns + constraints))
    new_table.create()

    migrate_utils.migrate_data(migrate_engine,
                               table,
                               new_table,
                               ['convergence'])
