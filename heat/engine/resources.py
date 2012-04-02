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

import logging
import os
import time
import base64
import string
from novaclient.v1_1 import client

from heat.db import api as db_api
from heat.common.config import HeatEngineConfigOpts

db_api.configure(HeatEngineConfigOpts())

logger = logging.getLogger('heat.engine.resources')

class Resource(object):
    CREATE_IN_PROGRESS = 'CREATE_IN_PROGRESS'
    CREATE_FAILED = 'CREATE_FAILED'
    CREATE_COMPLETE = 'CREATE_COMPLETE'
    DELETE_IN_PROGRESS = 'DELETE_IN_PROGRESS'
    DELETE_FAILED = 'DELETE_FAILED'
    DELETE_COMPLETE = 'DELETE_COMPLETE'
    UPDATE_IN_PROGRESS = 'UPDATE_IN_PROGRESS'
    UPDATE_FAILED = 'UPDATE_FAILED'
    UPDATE_COMPLETE = 'UPDATE_COMPLETE'

    def __init__(self, name, json_snippet, stack):
        self.t = json_snippet
        self.depends_on = []
        self.references = []
        self.references_resolved = False
        self.state = None
        self.stack = stack
        self.name = name
        self.instance_id = None
        self._nova = None
        if not self.t.has_key('Properties'):
            # make a dummy entry to prevent having to check all over the
            # place for it.
            self.t['Properties'] = {}

        stack.resolve_static_refs(self.t)
        stack.resolve_find_in_map(self.t)

    def nova(self):
        if self._nova:
            return self._nova

        username = self.stack.creds['username']
        password = self.stack.creds['password']
        tenant = self.stack.creds['tenant']
        auth_url = self.stack.creds['auth_url']

        self._nova = client.Client(username, password, tenant, auth_url,
                                   service_type='compute', service_name='nova')
        return self._nova

    def start(self):
        for c in self.depends_on:
            #print '%s->%s.start()' % (self.name, self.stack.resources[c].name)
            self.stack.resources[c].start()

        self.stack.resolve_attributes(self.t)
        self.stack.resolve_joins(self.t)
        self.stack.resolve_base64(self.t)


    def state_set(self, new_state, reason="state changed"):
        if new_state != self.state:
            ev = {}
            ev['LogicalResourceId'] = self.name
            ev['PhysicalResourceId'] = self.name
            ev['StackId'] = self.stack.name
            ev['StackName'] = self.stack.name
            ev['ResourceStatus'] = new_state
            ev['ResourceStatusReason'] = reason
            ev['ResourceType'] = self.t['Type']
            ev['ResourceProperties'] = self.t['Properties']

            db_api.event_create(None, ev)
            self.state = new_state

    def stop(self):
        pass

    def reload(self):
        pass

    def FnGetRefId(self):
        '''
http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/intrinsic-function-reference-ref.html
        '''
        if self.instance_id != None:
            return unicode(self.instance_id)
        else:
            return unicode(self.name)

    def FnGetAtt(self, key):
        '''
http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/intrinsic-function-reference-getatt.html
        '''
        print '%s.GetAtt(%s)' % (self.name, key)
        return unicode('not-this-surely')

    def FnBase64(self, data):
        '''
http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/intrinsic-function-reference-base64.html
        '''
        return base64.b64encode(data)

class GenericResource(Resource):
    def __init__(self, name, json_snippet, stack):
        super(GenericResource, self).__init__(name, json_snippet, stack)

    def start(self):
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(GenericResource, self).start()
        print 'Starting GenericResource %s' % self.name


class ElasticIp(Resource):
    def __init__(self, name, json_snippet, stack):
        super(ElasticIp, self).__init__(name, json_snippet, stack)
        self.instance_id = ''

        if self.t.has_key('Properties') and self.t['Properties'].has_key('Domain'):
            logger.warn('*** can\'t support Domain %s yet' % (self.t['Properties']['Domain']))

    def start(self):
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(ElasticIp, self).start()
        self.instance_id = 'eip-000003'

    def FnGetRefId(self):
        return unicode('0.0.0.0')

    def FnGetAtt(self, key):
        return unicode(self.instance_id)

class ElasticIpAssociation(Resource):
    def __init__(self, name, json_snippet, stack):
        super(ElasticIpAssociation, self).__init__(name, json_snippet, stack)

        # note we only support already assigned ipaddress
        #
        # Done with:
        # nova-manage floating create 172.31.0.224/28
        # euca-allocate-address
        #

        if not self.t['Properties'].has_key('EIP'):
            logger.warn('*** can\'t support this yet')
        if self.t['Properties'].has_key('AllocationId'):
            logger.warn('*** can\'t support AllocationId %s yet' % (self.t['Properties']['AllocationId']))

    def FnGetRefId(self):
        if not self.t['Properties'].has_key('EIP'):
            return unicode('0.0.0.0')
        else:
            return unicode(self.t['Properties']['EIP'])

    def start(self):

        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(ElasticIpAssociation, self).start()
        logger.info('$ euca-associate-address -i %s %s' % (self.t['Properties']['InstanceId'],
                                                           self.t['Properties']['EIP']))

class Volume(Resource):
    def __init__(self, name, json_snippet, stack):
        super(Volume, self).__init__(name, json_snippet, stack)

    def start(self):
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(Volume, self).start()

        vol = self.nova().volumes.create(self.t['Properties']['Size'],
                                         display_name=self.name,
                                         display_description=self.name)
        self.instance_id = vol.id

    def stop(self):
        if self.state == self.DELETE_IN_PROGRESS or self.state == self.DELETE_COMPLETE:
            return
        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.stop(self)

        if self.instance_id != None:
            self.nova().volumes.delete(self.instance_id)
        self.state_set(self.DELETE_COMPLETE)

class VolumeAttachment(Resource):
    def __init__(self, name, json_snippet, stack):
        super(VolumeAttachment, self).__init__(name, json_snippet, stack)

    def start(self):

        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(VolumeAttachment, self).start()

        att = self.nova().volumes.create_server_volume(self.t['Properties']['InstanceId'],
                                                       self.t['Properties']['VolumeId'],
                                                       self.t['Properties']['Device'])
        self.instance_id = att.id
        self.state_set(self.CREATE_COMPLETE)

    def stop(self):
        if self.state == self.DELETE_IN_PROGRESS or self.state == self.DELETE_COMPLETE:
            return
        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.stop(self)

        if self.instance_id == None:
            self.nova().volumes.delete_server_volume(self.t['Properties']['InstanceId'],
                                                     self.instance_id)
        self.state_set(self.DELETE_COMPLETE)

class Instance(Resource):

    def __init__(self, name, json_snippet, stack):
        super(Instance, self).__init__(name, json_snippet, stack)

        if not self.t['Properties'].has_key('AvailabilityZone'):
            self.t['Properties']['AvailabilityZone'] = 'nova'
        self.itype_oflavor = {'t1.micro': 'm1.tiny',
            'm1.small': 'm1.small',
            'm1.medium': 'm1.medium',
            'm1.large': 'm1.large',
            'm1.xlarge': 'm1.tiny', # TODO(sdake)
            'm2.xlarge': 'm1.xlarge',
            'm2.2xlarge': 'm1.large',
            'm2.4xlarge': 'm1.large',
            'c1.medium': 'm1.medium',
            'c1.4xlarge': 'm1.large',
            'cc2.8xlarge': 'm1.large',
            'cg1.4xlarge': 'm1.large'}


    def FnGetAtt(self, key):
        print '%s.GetAtt(%s)' % (self.name, key)

        if key == 'AvailabilityZone':
            return unicode(self.t['Properties']['AvailabilityZone'])
        else:
            # TODO PrivateDnsName, PublicDnsName, PrivateIp, PublicIp
            return unicode('not-this-surely')


    def start(self):
        def _null_callback(p, n, out):
            """
            Method to silence the default M2Crypto.RSA.gen_key output.
            """
            pass

        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        Resource.start(self)

        props = self.t['Properties']
        if not props.has_key('KeyName'):
            props['KeyName'] = 'default-key-name'
        if not props.has_key('InstanceType'):
            props['InstanceType'] = 's1.large'
        if not props.has_key('ImageId'):
            props['ImageId'] = 'F16-x86_64'

        for p in props:
            if p == 'UserData':
                new_script = []
                script_lines = props[p].split('\n')

                for l in script_lines:
                    if '#!/' in l:
                        new_script.append(l)
                        self.insert_package_and_services(self.t, new_script)
                    else:
                        new_script.append(l)
                userdata = '\n'.join(new_script)

        try:
            con = self.t['Metadata']["AWS::CloudFormation::Init"]['config']
            for st in con['services']:
                for s in con['services'][st]:
                    print 'service start %s_%s' % (self.name, s)
        except KeyError as e:
            # if there is no config then no services.
            pass

        # TODO(sdake)
        # heat API should take care of these conversions and feed them into
        # heat engine in an openstack specific json format

        flavor = self.itype_oflavor[self.t['Properties']['InstanceType']]
        distro_name = self.stack.parameter_get('LinuxDistribution')
        key_name = self.t['Properties']['KeyName']
        image_name = self.t['Properties']['ImageId']

        image_list = self.nova().images.list()
        for o in image_list:
            if o.name == image_name:
                image_id = o.id

        flavor_list = self.nova().flavors.list()
        for o in flavor_list:
            if o.name == flavor:
                flavor_id = o.id

        server = self.nova().servers.create(name=self.name, image=image_id,
                                            flavor=flavor_id, key_name=key_name,
                                            userdata=self.FnBase64(userdata))
        while server.status == 'BUILD':
            server.get()
            time.sleep(0.1)
        if server.status == 'ACTIVE':
            self.state_set(self.CREATE_COMPLETE)
            self.instance_id = server.id
        else:
            self.state_set(self.CREATE_FAILED)

    def stop(self):

        if self.state == self.DELETE_IN_PROGRESS or self.state == self.DELETE_COMPLETE:
            return
        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.stop(self)

        if self.instance_id == None:
            self.state_set(self.DELETE_COMPLETE)
            return

        server = self.nova().servers.get(self.instance_id)
        server.delete()
        self.instance_id = None
        self.state_set(self.DELETE_COMPLETE)


    def insert_package_and_services(self, r, new_script):

        try:
            con = r['Metadata']["AWS::CloudFormation::Init"]['config']
        except KeyError as e:
            return

        if con.has_key('packages'):
            for pt in con['packages']:
                if pt == 'yum':
                    for p in con['packages']['yum']:
                        new_script.append('yum install -y %s' % p)

        if con.has_key('services'):
            for st in con['services']:
                if st == 'systemd':
                    for s in con['services']['systemd']:
                        v = con['services']['systemd'][s]
                        if v['enabled'] == 'true':
                            new_script.append('systemctl enable %s.service' % s)
                        if v['ensureRunning'] == 'true':
                            new_script.append('systemctl start %s.service' % s)
                elif st == 'sysvinit':
                    for s in con['services']['sysvinit']:
                        v = con['services']['sysvinit'][s]
                        if v['enabled'] == 'true':
                            new_script.append('chkconfig %s on' % s)
                        if v['ensureRunning'] == 'true':
                            new_script.append('/etc/init.d/start %s' % s)
