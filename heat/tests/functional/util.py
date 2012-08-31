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
import errno
from pkg_resources import resource_string

from nose.plugins.attrib import attr
from nose import with_setup
from nose.exc import SkipTest

from glance import client as glance_client
from novaclient.v1_1 import client
from heat import utils
from heat.engine import parser


class FuncUtils:

    # during nose test execution this file will be imported even if
    # the unit tag was specified
    try:
        os.environ['OS_AUTH_STRATEGY']
    except KeyError:
        raise SkipTest('OS_AUTH_STRATEGY not set, skipping functional test')

    if os.environ['OS_AUTH_STRATEGY'] != 'keystone':
        print 'keystone authentication required'
        assert False

    creds = dict(username=os.environ['OS_USERNAME'],
            password=os.environ['OS_PASSWORD'],
            tenant=os.environ['OS_TENANT_NAME'],
            auth_url=os.environ['OS_AUTH_URL'],
            strategy=os.environ['OS_AUTH_STRATEGY'])
    dbusername = 'testuser'
    stackname = 'teststack'

    # this test is in heat/tests/functional, so go up 3 dirs
    basepath = os.path.abspath(
            os.path.dirname(os.path.realpath(__file__)) + '/../../..')

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sftp = None
    novaclient = None
    glanceclient = None

    def get_ssh_client(self):
        if self.ssh.get_transport() != None:
            return self.ssh
        return None

    def get_sftp_client(self):
        if self.sftp != None:
            return self.sftp
        return None

    def get_nova_client(self):
        if self.novaclient != None:
            return self.novaclient
        return None

    def get_glance_client(self):
        if self.glanceclient != None:
            return self.glanceclient
        return None

    def prepare_jeos(self, p_os, arch, type):
        imagename = p_os + '-' + arch + '-' + type

        self.glanceclient = glance_client.Client(host="0.0.0.0", port=9292,
            use_ssl=False, auth_tok=None, creds=self.creds)

        # skip creating jeos if image already available
        if not self.poll_glance(self.glanceclient, imagename, False):
            if os.geteuid() != 0:
                print 'test must be run as root to create jeos'
                assert False

            # -d: debug, -G: register with glance
            subprocess.call(['heat-jeos', '-d', '-G', 'create', imagename])

            # Nose seems to change the behavior of the subprocess call to be
            # asynchronous. So poll glance until image is registered.
            self.poll_glance(self.glanceclient, imagename, True)

    def poll_glance(self, gclient, imagename, block):
        imagelistname = None
        tries = 0
        while imagelistname != imagename:
            tries += 1
            assert tries < 50
            if block:
                time.sleep(15)
            print "Checking glance for image registration"
            imageslist = gclient.get_images()
            for x in imageslist:
                imagelistname = x['name']
                if imagelistname == imagename:
                    print "Found image registration for %s" % imagename
                    # technically not necessary, but glance registers image
                    # before completely through with its operations
                    time.sleep(10)
                    return True
            if not block:
                break
        return False

    def create_stack(self, template_file, distribution):
        self.novaclient = client.Client(self.creds['username'],
            self.creds['password'], self.creds['tenant'],
            self.creds['auth_url'], service_type='compute')

        keyname = self.novaclient.keypairs.list().pop().name

        subprocess.call(['heat', '-d', 'create', self.stackname,
            '--template-file=' + self.basepath +
            '/templates/' + template_file,
            '--parameters=InstanceType=m1.xlarge;DBUsername=' +
            self.dbusername +
            ';DBPassword=' + os.environ['OS_PASSWORD'] +
            ';KeyName=' + keyname +
            ';LinuxDistribution=' + distribution])

        print "Waiting for OpenStack to initialize and assign network address"
        ip = None
        tries = 0
        while ip is None:
            tries += 1
            assert tries < 500
            time.sleep(10)

            for server in self.novaclient.servers.list():
                # TODO: get PhysicalResourceId instead
                if server.name == 'WikiDatabase':
                    address = server.addresses
                    print "Status: %s" % server.status
                    if address:
                        ip = address.items()[0][1][0]['addr']
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
                assert tries < 50
            else:
                print 'SSH daemon response detected'
                break

        tries = 0
        while True:
            try:
                tries += 1
                assert tries < 50
                self.ssh.connect(ip, username='ec2-user', allow_agent=True,
                    look_for_keys=True, password='password')
            except paramiko.AuthenticationException:
                print 'Authentication error'
                time.sleep(2)
            except Exception, e:
                if e.errno != errno.EHOSTUNREACH:
                    raise
                print 'Preparing to connect over SSH'
                time.sleep(2)
            else:
                print 'SSH connected'
                break
        self.sftp = self.ssh.open_sftp()

        tries = 0
        while True:
            try:
                self.sftp.stat('/var/lib/cloud/instance/boot-finished')
            except IOError, e:
                tries += 1
                if e.errno == errno.ENOENT:
                    assert tries < 50
                    print "Boot not finished yet..."
                    time.sleep(15)
                else:
                    print e.errno
                    raise
            else:
                print "Guest fully booted"
                break

    def check_cfntools(self):
        stdin, stdout, stderr = \
            self.ssh.exec_command('cd /opt/aws/bin; sha1sum *')
        files = stdout.readlines()

        cfn_tools_files = ['cfn-init', 'cfn-hup', 'cfn-signal',
                'cfn-get-metadata', 'cfn_helper.py']

        cfntools = {}
        for file in cfn_tools_files:
            file_data = resource_string('heat_jeos', 'cfntools/' + file)
            sha = hashlib.sha1(file_data).hexdigest()
            cfntools[file] = sha

        # 1. make sure installed cfntools SHA match VM's version
        for x in range(len(files)):
            data = files.pop().split('  ')
            cur_file = data[1].rstrip()
            if cur_file in cfn_tools_files:
                assert data[0] == cfntools[cur_file]
        print 'VM cfntools integrity verified'

    def wait_for_provisioning(self):
        print "Waiting for provisioning to complete"
        tries = 0
        while True:
            try:
                self.sftp.stat('/var/lib/cloud/instance/provision-finished')
            except IOError, e:
                tries += 1
                if e.errno == errno.ENOENT:
                    assert tries < 500
                    print "Provisioning not finished yet..."
                    time.sleep(15)
                else:
                    print e.errno
                    raise
            else:
                print "Provisioning completed"
                break

    def check_user_data(self, template_file):
        transport = self.ssh.get_transport()
        channel = transport.open_session()
        channel.get_pty()
        channel.invoke_shell()  # sudo requires tty
        channel.sendall('sudo chmod 777 \
            sudo chmod 777 /var/lib/cloud/instance/user-data.txt.i\n')
        time.sleep(1)  # necessary for sendall to complete

        f = open(self.basepath + '/templates/' + template_file)
        t = json.loads(f.read())
        f.close()

        template = parser.Template(t)
        params = parser.Parameters('test', t,
                                   {'KeyName': 'required_parameter',
                                    'DBUsername': self.dbusername,
                                    'DBPassword': self.creds['password']})

        stack = parser.Stack(None, 'test', template, params)
        parsed_t = stack.resolve_static_data(t)
        remote_file = self.sftp.open('/var/lib/cloud/data/cfn-userdata')
        remote_file_list = remote_file.read().split('\n')
        remote_file_list_u = map(unicode, remote_file_list)
        remote_file.close()

        t_data = parsed_t['Resources']['WikiDatabase']['Properties']
        t_data = t_data['UserData']['Fn::Base64']['Fn::Join'].pop()
        joined_t_data = ''.join(t_data)
        t_data_list = joined_t_data.split('\n')
        # must match user data injection
        t_data_list.insert(len(t_data_list) - 1,
                u'touch /var/lib/cloud/instance/provision-finished')

        assert t_data_list == remote_file_list_u

        remote_file = self.sftp.open('/var/lib/cloud/instance/user-data.txt.i')
        msg = email.message_from_file(remote_file)
        remote_file.close()

        filepaths = {
            'cloud-config': self.basepath + '/heat/cloudinit/config',
            'part-handler.py': self.basepath +
            '/heat/cloudinit/part-handler.py'
        }

        # check multipart mime accuracy
        for part in msg.walk():
            # multipart/* are just containers
            if part.get_content_maintype() == 'multipart':
                continue

            file = part.get_filename()
            data = part.get_payload()

            if file in filepaths.keys():
                with open(filepaths[file]) as f:
                    assert data == f.read()

    def cleanup(self):
        self.ssh.close()
        subprocess.call(['heat', 'delete', self.stackname])

if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
