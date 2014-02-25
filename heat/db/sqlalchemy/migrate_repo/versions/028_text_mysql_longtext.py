
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
from sqlalchemy.dialects import mysql
from sqlalchemy import types as sqltypes


def upgrade(migrate_engine):
    if migrate_engine.name != 'mysql':
        return

    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    stack.c.parameters.alter(type=mysql.LONGTEXT())

    resource = sqlalchemy.Table('resource', meta, autoload=True)
    resource.c.rsrc_metadata.alter(type=mysql.LONGTEXT())

    watch_rule = sqlalchemy.Table('watch_rule', meta, autoload=True)
    watch_rule.c.rule.alter(type=mysql.LONGTEXT())

    watch_data = sqlalchemy.Table('watch_data', meta, autoload=True)
    watch_data.c.data.alter(type=mysql.LONGTEXT())


def downgrade(migrate_engine):
    if migrate_engine.name != 'mysql':
        return

    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    stack.c.parameters.alter(type=sqltypes.TEXT())

    resource = sqlalchemy.Table('resource', meta, autoload=True)
    resource.c.rsrc_metadata.alter(type=sqltypes.TEXT())

    watch_rule = sqlalchemy.Table('watch_rule', meta, autoload=True)
    watch_rule.c.rule.alter(type=sqltypes.TEXT())

    watch_data = sqlalchemy.Table('watch_data', meta, autoload=True)
    watch_data.c.data.alter(type=sqltypes.TEXT())
