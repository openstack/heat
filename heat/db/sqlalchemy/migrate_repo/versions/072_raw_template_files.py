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

from heat.db.sqlalchemy import types


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)
    raw_template_files = sqlalchemy.Table(
        'raw_template_files', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer,
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('files', types.Json),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        mysql_engine='InnoDB',
        mysql_charset='utf8'

    )
    raw_template_files.create()

    raw_template = sqlalchemy.Table('raw_template', meta, autoload=True)
    files_id = sqlalchemy.Column(
        'files_id', sqlalchemy.Integer(),
        sqlalchemy.ForeignKey('raw_template_files.id',
                              name='raw_tmpl_files_fkey_ref'))
    files_id.create(raw_template)
