#!/usr/bin/env python

import cloudinit
import sys
import os
import stat
import subprocess
import datetime

path = None

try:
    path = cloudinit.get_cpath('data')
except AttributeError:
    # pre 0.6.0 - user data executed via cloudinit, not this helper
    with open('/var/log/heat-provision.log', 'w') as log:
        log.write('Unable to log provisioning, need a newer version of'
                  ' cloud-init\n')
        sys.exit(0)

os.chmod(path + '/cfn-userdata', stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

with open('/var/log/heat-provision.log', 'w') as log:
    log.write('Provision began: %s\n' % datetime.datetime.now())
    log.flush()
    p = subprocess.Popen(path + '/cfn-userdata', stdout=log, stderr=log)
    p.wait()
    log.write('Provision done: %s\n' % datetime.datetime.now())
    if p.returncode:
        sys.exit(p.returncode)

with open(cloudinit.get_ipath_cur() + '/provision-finished', 'w') as log:
    log.write('%s\n' % datetime.datetime.now())
