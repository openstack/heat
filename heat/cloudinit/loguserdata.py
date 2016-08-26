#!/bin/bash
#
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
"true" '''\'
# NOTE(vgridnev): ubuntu trusty by default has python3,
# but pkg_resources can't be imported.
echo "import pkg_resources" | python3 2>/dev/null
has_py3=$?
if [ $has_py3 = 0 ]; then
    interpreter="python3"
else
    interpreter="python"
fi
exec $interpreter "$0"
'''

import datetime
from distutils import version
import errno
import logging
import os
import re
import subprocess
import sys

import pkg_resources


VAR_PATH = '/var/lib/heat-cfntools'
LOG = logging.getLogger('heat-provision')


def chk_ci_version():
    try:
        v = version.LooseVersion(
            pkg_resources.get_distribution('cloud-init').version)
        return v >= version.LooseVersion('0.6.0')
    except Exception:
        pass
    data = subprocess.Popen(['cloud-init', '--version'],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE).communicate()
    if data[0]:
        raise Exception()
    # data[1] has such format: 'cloud-init 0.7.5\n', need to parse version
    v = re.split(' |\n', data[1])[1].split('.')
    return tuple(v) >= tuple(['0', '6', '0'])


def init_logging():
    LOG.setLevel(logging.INFO)
    LOG.addHandler(logging.StreamHandler())
    fh = logging.FileHandler("/var/log/heat-provision.log")
    os.chmod(fh.baseFilename, int("600", 8))
    LOG.addHandler(fh)


def call(args):

    class LogStream(object):

        def write(self, data):
            LOG.info(data)

    LOG.info('%s\n', ' '.join(args))  # noqa
    try:
        ls = LogStream()
        p = subprocess.Popen(args, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        data = p.communicate()
        if data:
            for x in data:
                ls.write(x)
    except OSError:
        ex_type, ex, tb = sys.exc_info()
        if ex.errno == errno.ENOEXEC:
            LOG.error('Userdata empty or not executable: %s', ex)
            return os.EX_OK
        else:
            LOG.error('OS error running userdata: %s', ex)
            return os.EX_OSERR
    except Exception:
        ex_type, ex, tb = sys.exc_info()
        LOG.error('Unknown error running userdata: %s', ex)
        return os.EX_SOFTWARE
    return p.returncode


def main():

    try:
        if not chk_ci_version():
            # pre 0.6.0 - user data executed via cloudinit, not this helper
            LOG.error('Unable to log provisioning, need a newer version of '
                      'cloud-init')
            return -1
    except Exception:
        LOG.warning('Can not determine the version of cloud-init. It is '
                    'possible to get errors while logging provisioning.')

    userdata_path = os.path.join(VAR_PATH, 'cfn-userdata')
    os.chmod(userdata_path, int("700", 8))

    LOG.info('Provision began: %s', datetime.datetime.now())
    returncode = call([userdata_path])
    LOG.info('Provision done: %s', datetime.datetime.now())
    if returncode:
        return returncode


if __name__ == '__main__':
    init_logging()

    code = main()
    if code:
        LOG.error('Provision failed with exit code %s', code)
        sys.exit(code)

    provision_log = os.path.join(VAR_PATH, 'provision-finished')
    # touch the file so it is timestamped with when finished
    with open(provision_log, 'a'):
        os.utime(provision_log, None)
