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


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    resource = sqlalchemy.Table('resource', meta, autoload=True)
    resource_properties_data = sqlalchemy.Table('resource_properties_data',
                                                meta, autoload=True)
    attr_data_id = sqlalchemy.Column('attr_data_id',
                                     sqlalchemy.Integer)
    attr_data_id.create(resource)
    res_fkey = constraint.ForeignKeyConstraint(
        columns=[resource.c.attr_data_id],
        refcolumns=[resource_properties_data.c.id],
        name='rsrc_attr_data_ref')
    res_fkey.create()
