#!/usr/bin/env python
from migrate.versioning.shell import main
import migrate.exceptions

if __name__ == '__main__':
    import os.path
    migrate_repo_path = os.path.join(os.path.dirname(__file__),
                                     'migrate_repo')

    try:
        main(url='mysql://heat:heat@localhost/heat', debug='False',
             repository=migrate_repo_path)
    except migrate.exceptions.DatabaseAlreadyControlledError:
        print 'Database already version controlled.'
