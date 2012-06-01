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


"""Functional test case that utilizes the bin/heat CLI tool"""

import sys
import os
import optparse
import paramiko
import subprocess
import hashlib
import email
import json
import time  # for sleep
import nose

from nose.plugins.attrib import attr
from nose import with_setup

from novaclient.v1_1 import client
from glance import client as glance_client
from heat import utils
from heat.engine import parser


class TestBinHeat():
    """Functional tests for the bin/heat CLI tool"""

    def setUp(self):
        if os.geteuid() != 0:
            print 'test must be run as root'
            assert False

        if os.environ['OS_AUTH_STRATEGY'] != 'keystone':
            print 'keystone authentication required'
            assert False

        # this test is in heat/tests/functional, so go up 3 dirs
        self.basepath = os.path.abspath(
                os.path.dirname(os.path.realpath(__file__)) + '/../../..')

    @attr(speed='slow')
    @attr(tag=['func', 'jeos'])
    def test_jeos_create(self):
        # 0. Verify JEOS and cloud init
        args = ('F16', 'x86_64', 'cfntools')

        creds = dict(username=os.environ['OS_USERNAME'],
                password=os.environ['OS_PASSWORD'],
                tenant=os.environ['OS_TENANT_NAME'],
                auth_url=os.environ['OS_AUTH_URL'],
                strategy=os.environ['OS_AUTH_STRATEGY'])
        dbusername = 'testuser'

        subprocess.call(['heat', '-d', 'jeos-create',
            args[0], args[1], args[2]])

        gclient = glance_client.Client(host="0.0.0.0", port=9292,
            use_ssl=False, auth_tok=None, creds=creds)

        # Nose seems to change the behavior of the subprocess call to be
        # asynchronous. So poll glance until image is registered.
        imagename = '-'.join(str(i) for i in args)
        imagelistname = None
        tries = 0
        while imagelistname != imagename:
            tries += 1
            assert tries < 5000
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

        nt = client.Client(os.environ['OS_USERNAME'],
            os.environ['OS_PASSWORD'], os.environ['OS_TENANT_NAME'],
            os.environ['OS_AUTH_URL'], service_type='compute')

        keyname = nt.keypairs.list().pop().name

        subprocess.call(['heat', '-d', 'create', 'teststack',
            '--template-file=' + self.basepath +
            '/templates/WordPress_Single_Instance.template',
            '--parameters=InstanceType=m1.xlarge;DBUsername=' + dbusername +
            ';DBPassword=' + os.environ['OS_PASSWORD'] +
            ';KeyName=' + keyname])

        print "Waiting for OpenStack to initialize and assign network address"
        ip = None
        tries = 0
        while ip is None:
            tries += 1
            assert tries < 500
            time.sleep(10)

            for server in nt.servers.list():
                if server.name == 'WikiDatabase':  # TODO: get from template
                    address = server.addresses
                    print "Status: %s" % server.status
                    if address:
                        ip = address['wordpress'][0]['addr']
                        print 'IP found:', ip
                        break
                    elif server.status == 'ERROR':
                        print 'Heat error? Aborting'
                        assert False
                        return

        tries = 0
        while True:
            try:
                subprocess.check_output(['nc', '-z', ip, '22'])
            except Exception:
                print 'SSH not up yet...'
                time.sleep(10)
                tries += 1
                assert tries < 100
            else:
                print 'SSH daemon response detected'
                time.sleep(5)  # yuck, sometimes SSH is not *really* up
                break

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username='ec2-user', allow_agent=True,
                look_for_keys=True, password='password')
        sftp = ssh.open_sftp()

        tries = 0
        while True:
            try:
                sftp.stat('/var/lib/cloud/instance/boot-finished')
            except IOError, e:
                tries += 1
                if e[0] == 2:
                    assert tries < 40
                    print "Boot not finished yet..."
                    time.sleep(15)
                else:
                    raise
            else:
                print "boot-finished file found, start host checks"
                break

        stdin, stdout, stderr = ssh.exec_command('cd /opt/aws/bin; sha1sum *')
        files = stdout.readlines()

        cfn_tools_files = ['cfn-init', 'cfn-hup', 'cfn-signal',
                'cfn-get-metadata', 'cfn_helper.py']

        cfntools = {}
        for file in cfn_tools_files:
            with open(self.basepath + '/heat/cfntools/' + file, 'rb') as f:
                sha = hashlib.sha1(f.read()).hexdigest()
                cfntools[file] = sha

        # 1. make sure cfntools SHA in tree match VM's version
        for x in range(len(files)):
            data = files.pop().split('  ')
            cur_file = data[1].rstrip()
            if cur_file in cfn_tools_files:
                assert data[0] == cfntools[cur_file]

        # 2. ensure wordpress was installed
        wp_file = '/etc/wordpress/wp-config.php'
        stdin, stdout, sterr = ssh.exec_command('ls ' + wp_file)
        result = stdout.readlines().pop().rstrip()
        assert result == wp_file

        # 3. check multipart mime accuracy
        transport = ssh.get_transport()
        channel = transport.open_session()
        channel.get_pty()
        channel.invoke_shell()  # sudo requires tty
        channel.sendall('sudo chmod 777 \
            /var/lib/cloud/instance/scripts/startup; \
            sudo chmod 777 /var/lib/cloud/instance/user-data.txt.i\n')
        time.sleep(1)  # necessary for sendall to complete

        filepaths = {
            'cloud-config': self.basepath + '/heat/cloudinit/config',
            'part-handler.py': self.basepath +
            '/heat/cloudinit/part-handler.py'
        }
        f = open(self.basepath +
            '/templates/WordPress_Single_Instance.template')
        t = json.loads(f.read())
        f.close()

        params = {}
        params['KeyStoneCreds'] = None
        t['Parameters']['KeyName']['Value'] = keyname
        t['Parameters']['DBUsername']['Value'] = dbusername
        t['Parameters']['DBPassword']['Value'] = creds['password']

        stack = parser.Stack('test', t, 0, params)
        parsed_t = stack.resolve_static_refs(t)
        remote_file = sftp.open('/var/lib/cloud/instance/scripts/startup')
        remote_file_list = remote_file.read().split('\n')
        remote_file.close()

        t_data = parsed_t['Resources']['WikiDatabase']['Properties']
        t_data = t_data['UserData']['Fn::Base64']['Fn::Join'].pop()
        joined_t_data = ''.join(t_data)
        t_data_list = joined_t_data.split('\n')

        assert t_data_list == remote_file_list

        remote_file = sftp.open('/var/lib/cloud/instance/user-data.txt.i')
        msg = email.message_from_file(remote_file)
        remote_file.close()

        for part in msg.walk():
            # multipart/* are just containers
            if part.get_content_maintype() == 'multipart':
                continue

            file = part.get_filename()
            data = part.get_payload()

            if file in filepaths.keys():
                with open(filepaths[file]) as f:
                    assert data == f.read()

        # cleanup
        ssh.close()
        subprocess.call(['heat', 'delete', 'teststack'])

if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
