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

    resource_properties_data = sqlalchemy.Table(
        'resource_properties_data', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer,
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('data', types.Json),
        sqlalchemy.Column('encrypted', sqlalchemy.Boolean),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )
    resource_properties_data.create()

    resource = sqlalchemy.Table('resource', meta, autoload=True)
    rsrc_prop_data_id = sqlalchemy.Column('rsrc_prop_data_id',
                                          sqlalchemy.Integer)
    rsrc_prop_data_id.create(resource)
    res_fkey = constraint.ForeignKeyConstraint(
        columns=[resource.c.rsrc_prop_data_id],
        refcolumns=[resource_properties_data.c.id],
        name='rsrc_rsrc_prop_data_ref')
    res_fkey.create()

    event = sqlalchemy.Table('event', meta, autoload=True)
    rsrc_prop_data_id = sqlalchemy.Column('rsrc_prop_data_id',
                                          sqlalchemy.Integer)
    rsrc_prop_data_id.create(event)
    ev_fkey = constraint.ForeignKeyConstraint(
        columns=[event.c.rsrc_prop_data_id],
        refcolumns=[resource_properties_data.c.id],
        name='ev_rsrc_prop_data_ref')
    ev_fkey.create()
