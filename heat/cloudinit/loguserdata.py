#!/usr/bin/env python

import errno
import datetime
import logging
import pkg_resources
import os
import subprocess
import sys

from distutils.version import LooseVersion


VAR_PATH = '/var/lib/heat-cfntools'
LOG = logging.getLogger('heat-provision')


def chk_ci_version():
    v = LooseVersion(pkg_resources.get_distribution('cloud-init').version)
    return v >= LooseVersion('0.6.0')


def init_logging():
    LOG.setLevel(logging.INFO)
    LOG.addHandler(logging.StreamHandler())
    fh = logging.FileHandler("/var/log/heat-provision.log")
    os.chmod(fh.baseFilename, 0o600)
    LOG.addHandler(fh)


def call(args):

    class LogStream:

        def write(self, data):
            LOG.info(data)

        def __getattr__(self, attr):
            return getattr(sys.stdout, attr)

    LOG.info('%s\n' % ' '.join(args))
    try:
        ls = LogStream()
        p = subprocess.Popen(args, stdout=ls, stderr=ls)
        p.wait()
    except OSError as ex:
        if ex.errno == errno.ENOEXEC:
            LOG.error('Userdata empty or not executable: %s\n' % str(ex))
            return os.EX_OK
        else:
            LOG.error('OS error running userdata: %s\n' % str(ex))
            return os.EX_OSERR
    except Exception as ex:
        LOG.error('Unknown error running userdata: %s\n' % str(ex))
        return os.EX_SOFTWARE
    return p.returncode


def main():

    if not chk_ci_version():
        # pre 0.6.0 - user data executed via cloudinit, not this helper
        LOG.info('Unable to log provisioning, need a newer version of'
                 ' cloud-init\n')
        return -1

    userdata_path = os.path.join(VAR_PATH, 'cfn-userdata')
    os.chmod(userdata_path, 0o700)

    LOG.info('Provision began: %s\n' % datetime.datetime.now())
    returncode = call([userdata_path])
    LOG.info('Provision done: %s\n' % datetime.datetime.now())
    if returncode:
        return returncode


if __name__ == '__main__':
    init_logging()

    code = main()
    if code:
        LOG.error('Provision failed with exit code %s' % code)
        sys.exit(code)

    provision_log = os.path.join(VAR_PATH, 'provision-finished')
    # touch the file so it is timestamped with when finished
    with file(provision_log, 'a'):
        os.utime(provision_log, None)
