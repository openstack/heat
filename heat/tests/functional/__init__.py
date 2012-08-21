# vim: tabstop=4 shiftwidth=4 softtabstop=4
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


import os
import subprocess
import time  # for sleep
import util as func_utils
from glance import client as glance_client


def setUp(self):
    if os.geteuid() != 0:
        print 'test must be run as root'
        assert False

    if os.environ['OS_AUTH_STRATEGY'] != 'keystone':
        print 'keystone authentication required'
        assert False

    prepare_jeos()


def prepare_jeos():
    # verify JEOS and cloud init
    args = ('F17', 'x86_64', 'cfntools')
    imagename = '-'.join(str(i) for i in args)
    creds = dict(username=os.environ['OS_USERNAME'],
            password=os.environ['OS_PASSWORD'],
            tenant=os.environ['OS_TENANT_NAME'],
            auth_url=os.environ['OS_AUTH_URL'],
            strategy=os.environ['OS_AUTH_STRATEGY'])

    # -d: debug, -G: register with glance
    subprocess.call(['heat-jeos', '-d', '-G', 'create', imagename])

    gclient = glance_client.Client(host="0.0.0.0", port=9292,
        use_ssl=False, auth_tok=None, creds=creds)

    # Nose seems to change the behavior of the subprocess call to be
    # asynchronous. So poll glance until image is registered.
    imagelistname = None
    tries = 0
    while imagelistname != imagename:
        tries += 1
        assert tries < 50
        time.sleep(15)
        print "Checking glance for image registration"
        imageslist = gclient.get_images()
        for x in imageslist:
            imagelistname = x['name']
            if imagelistname == imagename:
                print "Found image registration for %s" % imagename
                break

    # technically not necessary, but glance registers image before
    # completely through with its operations
    time.sleep(10)

# TODO: could do teardown and delete jeos
