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

from migrate.changeset import constraint
import sqlalchemy

from heat.db.sqlalchemy import types


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    resource = sqlalchemy.Table('resource', meta, autoload=True)
    raw_template = sqlalchemy.Table('raw_template', meta, autoload=True)

    needed_by = sqlalchemy.Column('needed_by', types.List)
    requires = sqlalchemy.Column('requires', types.List)
    replaces = sqlalchemy.Column('replaces', sqlalchemy.Integer)
    replaced_by = sqlalchemy.Column('replaced_by', sqlalchemy.Integer)
    current_template_id = sqlalchemy.Column('current_template_id',
                                            sqlalchemy.Integer)
    needed_by.create(resource)
    requires.create(resource)
    replaces.create(resource)
    replaced_by.create(resource)
    current_template_id.create(resource)

    fkey = constraint.ForeignKeyConstraint(
        columns=[resource.c.current_template_id],
        refcolumns=[raw_template.c.id],
        name='current_template_fkey_ref')
    fkey.create()
