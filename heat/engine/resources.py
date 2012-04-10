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

from novaclient.v1_1 import client

from heat.db import api as db_api

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
        self.state = None
        self.stack = stack
        self.name = name
        self.instance_id = None
        self._nova = {}
        if not self.t.has_key('Properties'):
            # make a dummy entry to prevent having to check all over the
            # place for it.
            self.t['Properties'] = {}

        stack.resolve_static_refs(self.t)
        stack.resolve_find_in_map(self.t)

    def nova(self, service_type='compute'):
        if self._nova.has_key(service_type):
            return self._nova[service_type]

        username = self.stack.creds['username']
        password = self.stack.creds['password']
        tenant = self.stack.creds['tenant']
        auth_url = self.stack.creds['auth_url']
        if service_type == 'compute':
            service_name = 'nova'
        else:
            service_name = None


        self._nova[service_type] = client.Client(username, password, tenant, auth_url,
                                   service_type=service_type, service_name=service_name)
        return self._nova[service_type]

    def start(self):
        print 'starting %s name:%s' % (self.t['Type'], self.name)

        self.stack.resolve_attributes(self.t)
        self.stack.resolve_joins(self.t)
        self.stack.resolve_base64(self.t)


    def state_set(self, new_state, reason="state changed"):
        if new_state != self.state:
            ev = {}
            ev['logical_resource_id'] = self.name
            ev['physical_resource_id'] = self.name
            ev['stack_id'] = self.stack.id
            ev['stack_name'] = self.stack.name
            ev['resource_status'] = new_state
            ev['resource_status_reason'] = reason
            ev['resource_type'] = self.t['Type']
            ev['resource_properties'] = self.t['Properties']
            new_stack = db_api.stack_create(None, ev)
            ev['stack_id'] = new_stack.id
            db_api.event_create(None, ev)
            self.state = new_state

    def stop(self):
        print 'stopping %s name:%s id:%s' % (self.t['Type'], self.name, self.instance_id)

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

        vol = self.nova('volume').volumes.create(self.t['Properties']['Size'],
                                                 display_name=self.name,
                                                 display_description=self.name)

        while vol.status == 'creating':
            eventlet.sleep(1)
            vol.get()
        if vol.status == 'available':
            self.state_set(self.CREATE_COMPLETE)
            self.instance_id = vol.id
        else:
            self.state_set(self.CREATE_FAILED)

    def stop(self):
        if self.state == self.DELETE_IN_PROGRESS or self.state == self.DELETE_COMPLETE:
            return

        if self.instance_id != None:
            vol = self.nova('volume').volumes.get(self.instance_id)
            if vol.status == 'in-use':
                print 'cant delete volume when in-use'
                return

        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.stop(self)

        if self.instance_id != None:
            self.nova('volume').volumes.delete(self.instance_id)
        self.state_set(self.DELETE_COMPLETE)

class VolumeAttachment(Resource):
    def __init__(self, name, json_snippet, stack):
        super(VolumeAttachment, self).__init__(name, json_snippet, stack)

    def start(self):

        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(VolumeAttachment, self).start()

        print 'Attaching InstanceId %s VolumeId %s Device %s' % (self.t['Properties']['InstanceId'],
                                                                 self.t['Properties']['VolumeId'],
                                                                 self.t['Properties']['Device'])
        va = self.nova().volumes.create_server_volume(server_id=self.t['Properties']['InstanceId'],
                                                       volume_id=self.t['Properties']['VolumeId'],
                                                       device=self.t['Properties']['Device'])

        vol = self.nova('volume').volumes.get(va.id)
        while vol.status == 'available' or vol.status == 'attaching':
            eventlet.sleep(1)
            vol.get()
        if vol.status == 'in-use':
            self.state_set(self.CREATE_COMPLETE)
            self.instance_id = va.id
        else:
            self.state_set(self.CREATE_FAILED)

    def stop(self):
        if self.state == self.DELETE_IN_PROGRESS or self.state == self.DELETE_COMPLETE:
            return
        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.stop(self)

        print 'VolumeAttachment un-attaching %s %s' % (self.t['Properties']['InstanceId'],
                                                       self.instance_id)

        self.nova().volumes.delete_server_volume(self.t['Properties']['InstanceId'],
                                                 self.t['Properties']['VolumeId'])

        vol = self.nova('volume').volumes.get(self.t['Properties']['VolumeId'])
        while vol.status == 'in-use':
            print 'trying to un-attach %s, but still %s' % (self.instance_id, vol.status)
            eventlet.sleep(1)
            vol.get()

        self.state_set(self.DELETE_COMPLETE)

class Instance(Resource):

    def __init__(self, name, json_snippet, stack):
        super(Instance, self).__init__(name, json_snippet, stack)
        self.ipaddress = '0.0.0.0'

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

        res = 'not-this-surely'
        if key == 'AvailabilityZone':
            res = self.t['Properties']['AvailabilityZone']
        elif key == 'PublicIp':
            res = self.ipaddress
        else:
            logger.warn('%s.GetAtt(%s) is not handled' % (self.name, key))

        # TODO(asalkeld) PrivateDnsName, PublicDnsName & PrivateIp

        return unicode(res)

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

        # TODO(asalkeld) this needs to go into the metadata server.
        try:
            con = self.t['Metadata']["AWS::CloudFormation::Init"]['config']
            for st in con['services']:
                for s in con['services'][st]:
                    pass
                    #print 'service start %s_%s' % (self.name, s)
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

        image_id = None
        image_list = self.nova().images.list()
        for o in image_list:
            if o.name == image_name:
                image_id = o.id

        # TODO(asalkeld) we need to test earlier whether the image_id exists.
        if image_id is None:
            raise 

        flavor_list = self.nova().flavors.list()
        for o in flavor_list:
            if o.name == flavor:
                flavor_id = o.id

        server = self.nova().servers.create(name=self.name, image=image_id,
                                            flavor=flavor_id, key_name=key_name,
                                            userdata=self.FnBase64(userdata))
        while server.status == 'BUILD':
            server.get()
            eventlet.sleep(1)
        if server.status == 'ACTIVE':
            self.state_set(self.CREATE_COMPLETE)
            self.instance_id = server.id

            # just record the first ipaddress
            for n in server.networks:
                self.ipaddress = server.networks[n][0]
                break
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
