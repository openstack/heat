#!/usr/bin/env python

import sys
import os
import stat
import subprocess
import datetime
import pkg_resources
import errno

path = '/var/lib/cloud/data'

ci_version = pkg_resources.get_distribution('cloud-init').version.split('.')
if ci_version[0] <= 0 and ci_version[1] < 6:
    # pre 0.6.0 - user data executed via cloudinit, not this helper
    with open('/var/log/heat-provision.log', 'w') as log:
        log.write('Unable to log provisioning, need a newer version of'
                  ' cloud-init\n')
        sys.exit(0)

os.chmod(os.path.join(path, 'cfn-userdata'),
         stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

with open('/var/log/heat-provision.log', 'w') as log:
    log.write('Provision began: %s\n' % datetime.datetime.now())
    log.flush()
    p = subprocess.Popen(os.path.join(path, 'cfn-userdata'),
                         stdout=log, stderr=log)
    p.wait()
    log.write('Provision done: %s\n' % datetime.datetime.now())
    if p.returncode:
        sys.exit(p.returncode)

try:
    os.makedirs('/var/lib/heat')
except OSError as e:
    if e.errno != errno.EEXIST:
        raise

with open('/var/lib/heat/provision-finished', 'w') as log:
    log.write('%s\n' % datetime.datetime.now())
