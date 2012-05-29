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

import base64
import eventlet
import logging
import os
import string
import json
import sys
from email import encoders
from email.message import Message
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from novaclient.exceptions import NotFound

from heat.engine.resources import Resource
from heat.common import exception

logger = logging.getLogger(__file__)
# If ../heat/__init__.py exists, add ../ to Python search path, so that
# it will override what happens to be installed in /usr/(local/)lib/python...
possible_topdir = os.path.normpath(os.path.join(os.path.abspath(sys.argv[0]),
                                   os.pardir,
                                   os.pardir))
if os.path.exists(os.path.join(possible_topdir, 'heat', '__init__.py')):
    sys.path.insert(0, possible_topdir)
    cloudinit_path = '%s/heat/%s/' % (possible_topdir, "cloudinit")
else:
    for p in sys.path:
        if 'heat' in p:
            cloudinit_path = '%s/heat/%s/' % (p, "cloudinit")
            break


class Instance(Resource):
    # AWS does not require KeyName and InstanceType but we seem to
    properties_schema = {'ImageId': {'Type': 'String',
                                    'Required': True},
                         'InstanceType': {'Type': 'String',
                                    'Required': True},
                         'KeyName': {'Type': 'String',
                                     'Required': True},
                         'AvailabilityZone': {'Type': 'String',
                                              'Default': 'nova'},
                         'DisableApiTermination': {'Type': 'String',
                                                   'Implemented': False},
                         'KernelId': {'Type': 'String',
                                      'Implemented': False},
                         'Monitoring': {'Type': 'Boolean',
                                        'Implemented': False},
                         'PlacementGroupName': {'Type': 'String',
                                                'Implemented': False},
                         'PrivateIpAddress': {'Type': 'String',
                                              'Implemented': False},
                         'RamDiskId': {'Type': 'String',
                                       'Implemented': False},
                         'SecurityGroups': {'Type': 'TuplesList',
                                              'Implemented': False},
                         'SecurityGroupIds': {'Type': 'CommaDelimitedList',
                                              'Implemented': False},
                         'SourceDestCheck': {'Type': 'Boolean',
                                             'Implemented': False},
                         'SubnetId': {'Type': 'String',
                                       'Implemented': False},
                         'Tags': {'Type': 'CommaDelimitedList',
                                          'Implemented': False},
                         'Tenancy': {'Type': 'String',
                                     'AllowedValues': ['dedicated', 'default'],
                                     'Implemented': False},
                         'UserData': {'Type': 'String'},
                         'Volumes': {'Type': 'CommaDelimitedList',
                                     'Implemented': False}}

    def __init__(self, name, json_snippet, stack):
        super(Instance, self).__init__(name, json_snippet, stack)
        self.ipaddress = '0.0.0.0'
        self.mime_string = None

        self.itype_oflavor = {'t1.micro': 'm1.tiny',
            'm1.small': 'm1.small',
            'm1.medium': 'm1.medium',
            'm1.large': 'm1.large',
            'm1.xlarge': 'm1.tiny',  # TODO(sdake)
            'm2.xlarge': 'm1.xlarge',
            'm2.2xlarge': 'm1.large',
            'm2.4xlarge': 'm1.large',
            'c1.medium': 'm1.medium',
            'c1.4xlarge': 'm1.large',
            'cc2.8xlarge': 'm1.large',
            'cg1.4xlarge': 'm1.large'}

    def FnGetAtt(self, key):

        res = None
        if key == 'AvailabilityZone':
            res = self.properties['AvailabilityZone']
        elif key == 'PublicIp':
            res = self.ipaddress
        elif key == 'PrivateDnsName':
            res = self.ipaddress
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        # TODO(asalkeld) PrivateDnsName, PublicDnsName & PrivateIp

        logger.info('%s.GetAtt(%s) == %s' % (self.name, key, res))
        return unicode(res)

    def _build_userdata(self, userdata):
        if not self.mime_string:
            # Build mime multipart data blob for cloudinit userdata
            mime_blob = MIMEMultipart()
            fp = open('%s/%s' % (cloudinit_path, 'config'), 'r')
            msg = MIMEText(fp.read(), _subtype='cloud-config')
            fp.close()
            msg.add_header('Content-Disposition', 'attachment',
                           filename='cloud-config')
            mime_blob.attach(msg)

            fp = open('%s/%s' % (cloudinit_path, 'part-handler.py'), 'r')
            msg = MIMEText(fp.read(), _subtype='part-handler')
            fp.close()
            msg.add_header('Content-Disposition', 'attachment',
                           filename='part-handler.py')
            mime_blob.attach(msg)

            if 'Metadata' in self.t:
                msg = MIMEText(json.dumps(self.t['Metadata']),
                               _subtype='x-cfninitdata')
                msg.add_header('Content-Disposition', 'attachment',
                               filename='cfn-init-data')
                mime_blob.attach(msg)

            if self.stack.metadata_server:
                msg = MIMEText(self.stack.metadata_server,
                               _subtype='x-cfninitdata')
                msg.add_header('Content-Disposition', 'attachment',
                               filename='cfn-metadata-server')
                mime_blob.attach(msg)

            msg = MIMEText(userdata, _subtype='x-shellscript')
            msg.add_header('Content-Disposition', 'attachment',
                           filename='startup')
            mime_blob.attach(msg)
            self.mime_string = mime_blob.as_string()

        return self.mime_string

    def create(self):
        def _null_callback(p, n, out):
            """
            Method to silence the default M2Crypto.RSA.gen_key output.
            """
            pass

        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        Resource.create(self)

        security_groups = self.properties.get('SecurityGroups')
        userdata = self.properties['UserData']
        flavor = self.itype_oflavor[self.properties['InstanceType']]
        key_name = self.properties['KeyName']

        keypairs = [k.name for k in self.nova().keypairs.list()]
        if key_name not in keypairs:
            raise exception.UserKeyPairMissing(key_name=key_name)

        image_name = self.properties['ImageId']
        image_id = None
        image_list = self.nova().images.list()
        for o in image_list:
            if o.name == image_name:
                image_id = o.id

        if image_id is None:
            logger.info("Image %s was not found in glance" % image_name)
            raise exception.ImageNotFound(image_name=image_name)

        flavor_list = self.nova().flavors.list()
        for o in flavor_list:
            if o.name == flavor:
                flavor_id = o.id

        server_userdata = self._build_userdata(userdata)
        server = self.nova().servers.create(name=self.name, image=image_id,
                                            flavor=flavor_id,
                                            key_name=key_name,
                                            security_groups=security_groups,
                                            userdata=server_userdata)
        while server.status == 'BUILD':
            server.get()
            eventlet.sleep(1)
        if server.status == 'ACTIVE':
            self.instance_id_set(server.id)
            self.state_set(self.CREATE_COMPLETE)
            # just record the first ipaddress
            for n in server.networks:
                self.ipaddress = server.networks[n][0]
                break
        else:
            raise exception.Error(server.status)

    def validate(self):
        '''
        Validate any of the provided params
        '''
        res = Resource.validate(self)
        if res:
            return res
        #check validity of key
        if self.stack.parms['KeyName']:
            keypairs = self.nova().keypairs.list()
            valid_key = False
            for k in keypairs:
                if k.name == self.stack.parms['KeyName']:
                    valid_key = True
            if not valid_key:
                return {'Error': \
                        'Provided KeyName is not registered with nova'}
        return None

    def reload(self):
        '''
        re-read the server's ipaddress so FnGetAtt works.
        '''
        try:
            server = self.nova().servers.get(self.instance_id)
            for n in server.networks:
                self.ipaddress = server.networks[n][0]
        except NotFound:
            self.ipaddress = '0.0.0.0'

        Resource.reload(self)

    def delete(self):
        if self.state == self.DELETE_IN_PROGRESS or \
           self.state == self.DELETE_COMPLETE:
            return
        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)
        try:
            server = self.nova().servers.get(self.instance_id)
        except NotFound:
            pass
        else:
            server.delete()
        self.instance_id = None
        self.state_set(self.DELETE_COMPLETE)
