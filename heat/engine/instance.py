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

import eventlet
import os
import json
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from novaclient.exceptions import NotFound

import heat
from heat.engine import resources
from heat.common import exception

from heat.openstack.common import log as logging

logger = logging.getLogger('heat.engine.instance')


class Restarter(resources.Resource):
    properties_schema = {'InstanceId': {'Type': 'String',
                                        'Required': True}}

    def _find_resource(self, instance_id):
        '''
        Return the resource with the specified instance ID, or None if it
        cannot be found.
        '''
        for resource in self.stack:
            if resource.instance_id == instance_id:
                return resource
        return None

    def alarm(self):
        self.calculate_properties()
        victim = self._find_resource(self.properties['InstanceId'])

        if victim is None:
            logger.info('%s Alarm, can not find instance %s' %
                    (self.name, self.properties['InstanceId']))
            return

        logger.info('%s Alarm, restarting resource: %s' %
                    (self.name, victim.name))
        self.stack.restart_resource(victim.name)


class Instance(resources.Resource):
    # AWS does not require KeyName and InstanceType but we seem to
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}

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
                         'SecurityGroups': {'Type': 'List'},
                         'SecurityGroupIds': {'Type': 'List',
                                              'Implemented': False},
                         'SourceDestCheck': {'Type': 'Boolean',
                                             'Implemented': False},
                         'SubnetId': {'Type': 'String',
                                       'Implemented': False},
                         'Tags': {'Type': 'List',
                                  'Schema': tags_schema},
                         'NovaSchedulerHints': {'Type': 'List',
                                                'Schema': tags_schema},
                         'Tenancy': {'Type': 'String',
                                     'AllowedValues': ['dedicated', 'default'],
                                     'Implemented': False},
                         'UserData': {'Type': 'String'},
                         'Volumes': {'Type': 'List',
                                     'Implemented': False}}

    def __init__(self, name, json_snippet, stack):
        super(Instance, self).__init__(name, json_snippet, stack)
        self.ipaddress = None
        self.mime_string = None

    def _set_ipaddress(self, networks):
        '''
        Read the server's IP address from a list of networks provided by Nova
        '''
        # Just record the first ipaddress
        for n in networks:
            self.ipaddress = networks[n][0]
            break

    def _ipaddress(self):
        '''
        Return the server's IP address, fetching it from Nova if necessary
        '''
        if self.ipaddress is None:
            try:
                server = self.nova().servers.get(self.instance_id)
            except NotFound as ex:
                logger.warn('Instance IP address not found (%s)' % str(ex))
            else:
                self._set_ipaddress(server.networks)

        return self.ipaddress or '0.0.0.0'

    def FnGetAtt(self, key):
        res = None
        if key == 'AvailabilityZone':
            res = self.properties['AvailabilityZone']
        elif key == 'PublicIp':
            res = self._ipaddress()
        elif key == 'PrivateDnsName':
            res = self._ipaddress()
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        # TODO(asalkeld) PrivateDnsName, PublicDnsName & PrivateIp

        logger.info('%s.GetAtt(%s) == %s' % (self.name, key, res))
        return unicode(res)

    def _build_userdata(self, userdata):
        if not self.mime_string:
            # Build mime multipart data blob for cloudinit userdata

            def make_subpart(content, filename, subtype=None):
                if subtype is None:
                    subtype = os.path.splitext(filename)[0]
                msg = MIMEText(content, _subtype=subtype)
                msg.add_header('Content-Disposition', 'attachment',
                               filename=filename)
                return msg

            def read_cloudinit_file(fn):
                with open(os.path.join(heat.__path__[0], 'cloudinit', fn),
                          'r') as fp:
                    return fp.read()

            attachments = [(read_cloudinit_file('config'), 'cloud-config'),
                           (read_cloudinit_file('part-handler.py'),
                            'part-handler.py'),
                           (userdata, 'cfn-userdata', 'x-cfninitdata'),
                           (read_cloudinit_file('loguserdata.sh'),
                            'loguserdata.sh', 'x-shellscript')]

            if 'Metadata' in self.t:
                attachments.append((json.dumps(self.metadata),
                                    'cfn-init-data', 'x-cfninitdata'))

            metadata_server = resources.Metadata.server()
            if metadata_server is not None:
                attachments.append((metadata_server,
                                    'cfn-metadata-server', 'x-cfninitdata'))

            subparts = [make_subpart(*args) for args in attachments]
            mime_blob = MIMEMultipart(_subparts=subparts)

            self.mime_string = mime_blob.as_string()

        return self.mime_string

    def handle_create(self):
        security_groups = self.properties.get('SecurityGroups')
        userdata = self.properties['UserData']
        userdata += '\ntouch /var/lib/cloud/instance/provision-finished\n'
        flavor = self.properties['InstanceType']
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

        tags = {}
        if self.properties['Tags']:
            for tm in self.properties['Tags']:
                tags[tm['Key']] = tm['Value']
        else:
            tags = None

        scheduler_hints = {}
        if self.properties['NovaSchedulerHints']:
            for tm in self.properties['NovaSchedulerHints']:
                scheduler_hints[tm['Key']] = tm['Value']
        else:
            scheduler_hints = None

        server_userdata = self._build_userdata(userdata)
        server = self.nova().servers.create(name=self.name, image=image_id,
                                            flavor=flavor_id,
                                            key_name=key_name,
                                            security_groups=security_groups,
                                            userdata=server_userdata,
                                            meta=tags,
                                            scheduler_hints=scheduler_hints)
        while server.status == 'BUILD':
            server.get()
            eventlet.sleep(1)
        if server.status == 'ACTIVE':
            self.instance_id_set(server.id)
            self._set_ipaddress(server.networks)
        else:
            raise exception.Error('%s instance[%s] status[%s]' %
                                  ('nova reported unexpected',
                                   self.name, server.status))

    def handle_update(self):
        return self.UPDATE_REPLACE

    def validate(self):
        '''
        Validate any of the provided params
        '''
        res = super(Instance, self).validate()
        if res:
            return res

        #check validity of key
        try:
            key_name = self.properties['KeyName']
        except ValueError:
            return
        else:
            keypairs = self.nova().keypairs.list()
            valid_key = False
            for k in keypairs:
                if k.name == key_name:
                    return
        return {'Error':
                'Provided KeyName is not registered with nova'}

    def handle_delete(self):
        '''
        Delete an instance, blocking until it is disposed by OpenStack
        '''
        if self.instance_id is None:
            return
        try:
            server = self.nova().servers.get(self.instance_id)
        except NotFound:
            pass
        else:
            server.delete()
            while server.status == 'ACTIVE':
                try:
                    server.get()
                except NotFound:
                    break
                eventlet.sleep(0.2)
        self.instance_id = None
