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


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    for tab_name in ['stack', 'resource', 'software_deployment']:
        table = sqlalchemy.Table(tab_name, meta, autoload=True)
        if migrate_engine.name == 'ibm_db_sa':
            status_reason = sqlalchemy.Column('new_status_reason',
                                              sqlalchemy.Text)
            table.create_column(status_reason)
            qry = table.select().execute().fetchall()
            for item in qry:
                values = {'new_status_reason': item.status_reason}
                update = table.update().where(
                    table.c.id == item.id).values(values)
                migrate_engine.execute(update)
            table.c.status_reason.drop()
            table.c.new_status_reason.alter(name='status_reason')
        else:
            table.c.status_reason.alter(type=sqlalchemy.Text)
