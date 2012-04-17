#!/usr/bin/env python
from migrate.versioning.shell import main
import migrate.exceptions

if __name__ == '__main__':
    try:
        main(url='mysql://heat:heat@localhost/heat', debug='False',
             repository='migrate_repo')
    except migrate.exceptions.DatabaseAlreadyControlledError:
        print 'Database already version controlled.'
