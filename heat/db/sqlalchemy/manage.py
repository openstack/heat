#!/usr/bin/env python
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
        config.readfp(open('/etc/heat/heat-engine.conf'))
        sql_connection = config.get('DEFAULT', 'sql_connection')
    except Exception:
        sql_connection = 'mysql://heat:heat@localhost/heat'

    try:
        main(url=sql_connection, debug='False', repository=migrate_repo_path)
    except migrate.exceptions.DatabaseAlreadyControlledError:
        print('Database already version controlled.')
