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
from lxml import etree

from nose.plugins.attrib import attr
from nose import with_setup
from nose.exc import SkipTest

from glance import client as glance_client
from novaclient.v1_1 import client as nova_client
from heat import utils
from heat.engine import parser
from heat import client as heat_client
from heat import boto_client as heat_client_boto
from keystoneclient.v2_0 import client


class Instance(object):
    def __init__(self, instance_name):
        self.name = 'teststack.%s' % instance_name

        # during nose test execution this file will be imported even if
        # the unit tag was specified
        try:
            os.environ['OS_AUTH_STRATEGY']
        except KeyError:
            raise SkipTest('OS_AUTH_STRATEGY unset, skipping functional test')

        if os.environ['OS_AUTH_STRATEGY'] != 'keystone':
            print 'keystone authentication required'
            assert False

        self.creds = dict(username=os.environ['OS_USERNAME'],
                password=os.environ['OS_PASSWORD'],
                tenant=os.environ['OS_TENANT_NAME'],
                auth_url=os.environ['OS_AUTH_URL'],
                strategy=os.environ['OS_AUTH_STRATEGY'])
        dbusername = 'testuser'
        stackname = 'teststack'

        # this test is in heat/tests/functional, so go up 3 dirs
        basepath = os.path.abspath(
                os.path.dirname(os.path.realpath(__file__)) + '/../../..')

        self.novaclient = nova_client.Client(self.creds['username'],
            self.creds['password'], self.creds['tenant'],
            self.creds['auth_url'], service_type='compute')

        self.ssh = paramiko.SSHClient()

        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        self.ip = None
        tries = 0
        while self.ip is None:
            servers = self.novaclient.servers.list()
            for server in servers:
                if server.name == self.name:
                    address = server.addresses
                    if address:
                        self.ip = address.items()[0][1][0]['addr']
                time.sleep(10)
                tries += 1
                assert tries < 500
            print 'Instance (%s) ip (%s) status (%s)' % (self.name, self.ip,
                 server.status)

        tries = 0
        while True:
            try:
                subprocess.check_output(['nc', '-z', self.ip, '22'])
            except Exception:
                print('Instance (%s) ip (%s) SSH not up yet, waiting...' %
                      (self.name, self.ip))
                time.sleep(10)
                tries += 1
                assert tries < 50
            else:
                print 'Instance (%s) ip (%s) SSH detected.' % (self.name,
                        self.ip)
                break

        tries = 0
        while True:
            try:
                tries += 1
                assert tries < 50
                self.ssh.connect(self.ip, username='ec2-user',
                    allow_agent=True, look_for_keys=True, password='password')
            except paramiko.AuthenticationException:
                print 'Authentication error'
                time.sleep(2)
            except Exception as e:
                if e.errno != errno.EHOSTUNREACH:
                    raise
                print('Instance (%s) ip (%s) connecting via SSH.' %
                      (self.name, self.ip))
                time.sleep(2)
            else:
                print('Instance (%s) ip (%s) connected via SSH.' %
                      (self.name, self.ip))
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
                    print("Instance (%s) ip (%s) not booted, waiting..." %
                          (self.name, self.ip))
                    time.sleep(15)
                else:
                    print e.errno
                    raise
            else:
                print("Instance (%s) ip (%s) finished booting." %
                      (self.name, self.ip))
                break

    def exec_command(self, cmd):
        return self.ssh.exec_command(cmd)

    def file_present(self, path):
        print "Verifying file '%s' exists" % path
        stdin, stdout, sterr = self.ssh.exec_command('ls "%s"' % path)
        lines = stdout.readlines()
        assert len(lines) == 1
        result = lines.pop().rstrip()
        return result == path

    def floating_ip_present(self):
        floating_ips = self.novaclient.floating_ips.list()
        for eip in floating_ips:
            if self.ip == eip.fixed_ip:
                return True
        return False

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
        print 'Instance (%s) cfntools integrity verified.' % self.name

    def wait_for_provisioning(self):
        print "Instance (%s) waiting for provisioning to complete." % self.name
        tries = 0
        while True:
            try:
                self.sftp.stat('/var/lib/cloud/instance/provision-finished')
            except IOError, e:
                tries += 1
                if e.errno == errno.ENOENT:
                    assert tries < 500
                    print("Instance (%s) provisioning incomplete, waiting..." %
                          self.name)
                    time.sleep(15)
                else:
                    print e.errno
                    raise
            else:
                print "Instance (%s) provisioning completed." % self.name
                break

    def check_user_data(self, template_file):
        return  # until TODO is fixed

#        transport = self.ssh.get_transport()
#        channel = transport.open_session()
#        channel.get_pty()
#        channel.invoke_shell()  # sudo requires tty
#        channel.sendall('sudo chmod 777 \
#            sudo chmod 777 /var/lib/cloud/instance/user-data.txt.i\n')
#        time.sleep(1)  # necessary for sendall to complete

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

        # TODO: make server name generic
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

    def get_ssh_client(self):
        if self.ssh.get_transport() != None:
            return self.ssh
        return None

    def get_sftp_client(self):
        if self.sftp != None:
            return self.sftp
        return None

    def close_ssh_client(self):
        self.ssh.close()


class Stack(object):
    def __init__(self, template_file, distribution, arch, jeos_type,
            stack_paramstr):

        self.prepare_jeos(distribution, arch, jeos_type)

        self.novaclient = nova_client.Client(self.creds['username'],
            self.creds['password'], self.creds['tenant'],
            self.creds['auth_url'], service_type='compute')

        keyname = self.novaclient.keypairs.list().pop().name

        self.heatclient = self._create_heat_client()

        assert self.heatclient

        full_paramstr = stack_paramstr + ';' + ';'.join(['KeyName=' + keyname,
                         'LinuxDistribution=' + distribution])
        template_params = optparse.Values({'parameters': full_paramstr})

        # Format parameters and create the stack
        parameters = {}
        parameters['StackName'] = self.stackname
        template_path = self.basepath + '/templates/' + template_file
        parameters['TemplateBody'] = open(template_path).read()
        parameters.update(self.heatclient.format_parameters(template_params))
        result = self.heatclient.create_stack(**parameters)

        self._check_create_result(result)

        alist = None
        tries = 0

        print 'Waiting for stack creation to be completed'
        while self.in_state('CREATE_IN_PROGRESS'):
            tries += 1
            assert tries < 500
            time.sleep(10)

        assert self.in_state('CREATE_COMPLETE')

    def _check_create_result(self, result):
        # Check result looks OK
        root = etree.fromstring(result)
        create_list = root.xpath('/CreateStackResponse/CreateStackResult')
        assert create_list
        assert len(create_list) == 1

        # Extract StackId from the result, and check the StackName part
        stackid = create_list[0].findtext('StackId')
        idname = stackid.split('/')[1]
        print "Checking %s contains name %s" % (stackid, self.stackname)
        assert idname == self.stackname

    def _create_heat_client(self):
        return heat_client.get_client('0.0.0.0', 8000,
            self.creds['username'], self.creds['password'],
            self.creds['tenant'], self.creds['auth_url'],
            self.creds['strategy'], None, None, False)

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

    novaclient = None
    glanceclient = None
    heatclient = None

    def in_state(self, state):
        stack_list = self.heatclient.list_stacks(StackName=self.stackname)
        root = etree.fromstring(stack_list)
        xpq = '//member[StackName="%s" and StackStatus="%s"]'
        alist = root.xpath(xpq % (self.stackname, state))
        return bool(alist)

    def cleanup(self):
        parameters = {'StackName': self.stackname}
        c = self.get_heat_client()
        c.delete_stack(**parameters)

    def get_nova_client(self):
        if self.novaclient != None:
            return self.novaclient
        return None

    def get_glance_client(self):
        if self.glanceclient != None:
            return self.glanceclient
        return None

    def get_heat_client(self):
        if self.heatclient != None:
            return self.heatclient
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

    def get_stack_output(self, output_key):
        '''
        Extract a specified output from the DescribeStacks details
        '''
        # Get the DescribeStacks result for this stack
        parameters = {'StackName': self.stackname}
        c = self.get_heat_client()
        result = c.describe_stacks(**parameters)
        return self._find_stack_output(result, output_key)

    def _find_stack_output(self, result, output_key):
        # Extract the OutputValue for the specified OutputKey
        root = etree.fromstring(result)
        output_list = root.xpath('//member[OutputKey="' + output_key + '"]')
        output = output_list.pop()
        value = output.findtext('OutputValue')
        return value

    def instance_phys_ids(self):
        events = self.heatclient.list_stack_events(StackName=self.stackname)
        root = etree.fromstring(events)
        xpq = ('//member[StackName="%s" and '
               'ResourceStatus="CREATE_COMPLETE" and '
               'ResourceType="AWS::EC2::Instance"]')
        alist = root.xpath(xpq % self.stackname)

        return [elem.findtext('PhysicalResourceId') for elem in alist]

    def response_xml_item(self, response, prefix, key):
        '''
        Extract response item via xpath prefix and key name
        we expect the prefix to map to a single Element item
        '''
        root = etree.fromstring(response)
        output_list = root.xpath(prefix)
        assert output_list
        assert len(output_list) == 1
        output = output_list.pop()
        value = output.findtext(key)
        return value


class StackBoto(Stack):
    '''
    Version of the Stack class which uses the boto client (hence AWS auth and
    the CFN API).
    '''
    def _check_create_result(self, result):
        pass

    def _create_heat_client(self):
        # Connect to the keystone client with the supplied credentials
        # and extract the ec2-credentials, so we can pass them into the
        # boto client
        keystone = client.Client(username=self.creds['username'],
                             password=self.creds['password'],
                             tenant_name=self.creds['tenant'],
                             auth_url=self.creds['auth_url'])
        ksusers = keystone.users.list()
        ksuid = [u.id for u in ksusers if u.name == self.creds['username']]
        assert len(ksuid) == 1

        ec2creds = keystone.ec2.list(ksuid[0])
        assert len(ec2creds) == 1
        assert ec2creds[0].access
        assert ec2creds[0].secret
        print "Got EC2 credentials from keystone"

        # most of the arguments passed to heat_client_boto are for
        # compatibility with the non-boto client wrapper, and are
        # actually ignored, only the port and credentials are used
        return heat_client_boto.get_client('0.0.0.0', 8000,
            self.creds['username'], self.creds['password'],
            self.creds['tenant'], self.creds['auth_url'],
            self.creds['strategy'], None, None, False,
            aws_access_key=ec2creds[0].access,
            aws_secret_key=ec2creds[0].secret)

    def in_state(self, state):
        stack_list = self.heatclient.list_stacks(StackName=self.stackname)
        this = [s for s in stack_list if s.stack_name == self.stackname][0]
        return this.resource_status == state

    def instance_phys_ids(self):
        events = self.heatclient.list_stack_events(StackName=self.stackname)

        def match(e):
            return (e.stack_name == self.stackname and
                    e.resource_status == "CREATE_COMPLETE" and
                    e.resource_type == "AWS::EC2::Instance")

        return [e.physical_resource_id for e in events if match(e)]

    def _find_stack_output(self, result, output_key):
        assert len(result) == 1

        for o in result[0].outputs:
            if o.key == output_key:
                return o.value


if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
