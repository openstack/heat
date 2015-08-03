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

from oslo_log import log as logging
import sqlalchemy
from sqlalchemy import dialects

from heat.common.i18n import _LW

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)
    if migrate_engine.name == 'mysql':
        if migrate_engine.dialect.server_version_info < (5, 6, 4):
            LOG.warn(_LW('Migration 065 could not be applied as the MySQl '
                         'server version is below 5.6.4. Once the server has '
                         'been upgraded this migration will need to be '
                         'manually applied.'))
            return
        # Note that this feature was only added in 5.6.4
        # see: http://docs.sqlalchemy.org/en/rel_0_9/dialects/mysql.html
        for tn in ['raw_template', 'user_creds', 'stack',
                   'resource', 'resource_data', 'event',
                   'watch_rule', 'watch_data', 'snapshot',
                   'software_deployment', 'software_config',
                   'sync_point', 'service', 'stack_tag']:
            table = sqlalchemy.Table(tn, meta, autoload=True)
            # Use the fsp parameter (fractional seconds parameter) to allow
            # subsecond timestamps.
            table.c.updated_at.alter(type=dialects.mysql.DATETIME(fsp=6))
            table.c.created_at.alter(type=dialects.mysql.DATETIME(fsp=6))
