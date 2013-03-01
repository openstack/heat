#!/usr/bin/env python

import sys
import os
import subprocess
import datetime
import pkg_resources
from distutils.version import LooseVersion

path = '/var/lib/heat-cfntools'


def chk_ci_version():
    v = LooseVersion(pkg_resources.get_distribution('cloud-init').version)
    return v >= LooseVersion('0.6.0')


def create_log(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0600)
    return os.fdopen(fd, 'w')


def call(args, log):
    log.write('%s\n' % ' '.join(args))
    log.flush()
    p = subprocess.Popen(args, stdout=log, stderr=log)
    p.wait()
    return p.returncode


def main(log):

    if not chk_ci_version():
        # pre 0.6.0 - user data executed via cloudinit, not this helper
        log.write('Unable to log provisioning, need a newer version of'
                  ' cloud-init\n')
        return -1

    userdata_path = os.path.join(path, 'cfn-userdata')
    os.chmod(userdata_path, 0700)

    log.write('Provision began: %s\n' % datetime.datetime.now())
    log.flush()
    returncode = call([userdata_path], log)
    log.write('Provision done: %s\n' % datetime.datetime.now())
    if returncode:
        return returncode


if __name__ == '__main__':
    with create_log('/var/log/heat-provision.log') as log:
        returncode = main(log)
        if returncode:
            log.write('Provision failed')
            sys.exit(returncode)

    userdata_path = os.path.join(path, 'provision-finished')
    with create_log(userdata_path) as log:
        log.write('%s\n' % datetime.datetime.now())
