#!/usr/bin/env python

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

from migrate.versioning.shell import main
import migrate.exceptions
import ConfigParser

if __name__ == '__main__':
    import os.path
    migrate_repo_path = os.path.join(os.path.dirname(__file__),
                                     'migrate_repo')

    # Try to get the config-file value for sql_connection
    # Note we can't use openstack.common.cfg because this also insists
    # on parsing the CLI, which we don't want here
    config = ConfigParser.SafeConfigParser()
    try:
        config = ConfigParser.SafeConfigParser()
        config.readfp(open('/etc/heat/heat.conf'))
        sql_connection = config.get('DEFAULT', 'sql_connection')
    except Exception:
        sql_connection = 'mysql://heat:heat@localhost/heat'

    try:
        main(url=sql_connection, debug='False', repository=migrate_repo_path)
    except migrate.exceptions.DatabaseAlreadyControlledError:
        print('Database already version controlled.')
