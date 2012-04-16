#!/usr/bin/env python
from migrate.versioning.shell import main

if __name__ == '__main__':
    main(url='mysql://heat:heat@localhost/heat', debug='False',
         repository='migrate_repo')
