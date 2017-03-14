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

import os

from oslo_db.sqlalchemy import migration as oslo_migration


INIT_VERSION = 70


def db_sync(engine, version=None):
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                        'migrate_repo')
    return oslo_migration.db_sync(engine, path, version,
                                  init_version=INIT_VERSION)


def db_version(engine):
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                        'migrate_repo')
    return oslo_migration.db_version(engine, path, INIT_VERSION)


def db_version_control(engine, version=None):
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                        'migrate_repo')
    return oslo_migration.db_version_control(engine, path, version)
