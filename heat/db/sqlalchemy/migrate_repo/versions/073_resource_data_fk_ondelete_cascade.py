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

# This is a placeholder for Liberty backports.
# Do not use this number for new Mitaka work.  New Mitaka work starts after
# all the placeholders.


import sqlalchemy

from migrate import ForeignKeyConstraint


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    resource_data = sqlalchemy.Table('resource_data', meta, autoload=True)
    resource = sqlalchemy.Table('resource', meta, autoload=True)

    for fk in resource_data.foreign_keys:
        if fk.column == resource.c.id:
            # delete the existing fk
            # and create with ondelete cascade and a proper name
            existing_fkey = ForeignKeyConstraint(
                columns=[resource_data.c.resource_id],
                refcolumns=[resource.c.id], name=fk.name)
            existing_fkey.drop()
            fkey = ForeignKeyConstraint(
                columns=[resource_data.c.resource_id],
                refcolumns=[resource.c.id],
                name="fk_resource_id", ondelete='CASCADE')
            fkey.create()
            break
