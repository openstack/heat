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

import migrate
import sqlalchemy

from heat.db.sqlalchemy import utils as migrate_utils


def upgrade(migrate_engine):
    if migrate_engine.name == 'sqlite':
        upgrade_sqlite(migrate_engine)
        return

    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    tmpl_table = sqlalchemy.Table('raw_template', meta, autoload=True)

    # drop constraint
    fkey = migrate.ForeignKeyConstraint(
        columns=[tmpl_table.c.predecessor],
        refcolumns=[tmpl_table.c.id],
        name='predecessor_fkey_ref')
    fkey.drop()
    tmpl_table.c.predecessor.drop()


def upgrade_sqlite(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    tmpl_table = sqlalchemy.Table('raw_template', meta, autoload=True)
    ignorecols = [tmpl_table.c.predecessor.name]
    new_template = migrate_utils.clone_table('new_raw_template',
                                             tmpl_table,
                                             meta, ignorecols=ignorecols)
    # migrate stacks to new table
    migrate_utils.migrate_data(migrate_engine,
                               tmpl_table,
                               new_template,
                               skip_columns=['predecessor'])
