
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
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    user_creds = sqlalchemy.Table('user_creds', meta, autoload=True)

    user_creds.c.service_user.drop()
    user_creds.c.service_password.drop()


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    user_creds = sqlalchemy.Table('user_creds', meta, autoload=True)

    service_user = sqlalchemy.Column('service_user',
                                     sqlalchemy.String(length=255))
    service_user.create(user_creds)
    service_password = sqlalchemy.Column('service_password',
                                         sqlalchemy.String(length=255))
    service_password.create(user_creds)
