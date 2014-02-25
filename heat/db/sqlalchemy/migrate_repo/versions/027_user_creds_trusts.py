
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

    # keystone IDs are 32 characters long, but the keystone DB schema
    # specifies varchar(64) so align with that here, for the trust_id
    # we encrypt it, so align with the 255 chars allowed for password
    trustor_user_id = sqlalchemy.Column('trustor_user_id',
                                        sqlalchemy.String(length=64))
    trust_id = sqlalchemy.Column('trust_id', sqlalchemy.String(length=255))
    trustor_user_id.create(user_creds)
    trust_id.create(user_creds)


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    user_creds = sqlalchemy.Table('user_creds', meta, autoload=True)
    user_creds.c.trustor_user_id.drop()
    user_creds.c.trust_id.drop()
