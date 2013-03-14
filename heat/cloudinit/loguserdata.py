#!/usr/bin/env python

import datetime
import pkg_resources
import os
import subprocess
import sys

from distutils.version import LooseVersion


VAR_PATH = '/var/lib/heat-cfntools'


def chk_ci_version():
    v = LooseVersion(pkg_resources.get_distribution('cloud-init').version)
    return v >= LooseVersion('0.6.0')


def create_log(log_path):
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT, 0600)
    return os.fdopen(fd, 'w')


def call(args, logger):
    logger.write('%s\n' % ' '.join(args))
    logger.flush()
    p = subprocess.Popen(args, stdout=logger, stderr=logger)
    p.wait()
    return p.returncode


def main(logger):

    if not chk_ci_version():
        # pre 0.6.0 - user data executed via cloudinit, not this helper
        logger.write('Unable to log provisioning, need a newer version of'
                     ' cloud-init\n')
        return -1

    userdata_path = os.path.join(VAR_PATH, 'cfn-userdata')
    os.chmod(userdata_path, 0700)

    logger.write('Provision began: %s\n' % datetime.datetime.now())
    logger.flush()
    returncode = call([userdata_path], logger)
    logger.write('Provision done: %s\n' % datetime.datetime.now())
    if returncode:
        return returncode


if __name__ == '__main__':
    with create_log('/var/log/heat-provision.log') as log:
        code = main(log)
        if code:
            log.write('Provision failed')
            sys.exit(code)

    provision_log = os.path.join(VAR_PATH, 'provision-finished')
    with create_log(provision_log) as log:
        log.write('%s\n' % datetime.datetime.now())
