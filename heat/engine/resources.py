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

from heat.common import exception
from heat.db import api as db_api
from heat.common.config import HeatEngineConfigOpts

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
        self.stack = stack
        self.name = name
        resource = db_api.resource_get_by_name_and_stack(None, name, stack.id)
        if resource:
            self.instance_id = resource.nova_instance
            self.state = resource.state
            self.id = resource.id
        else:
            self.instance_id = None
            self.state = None
            self.id = None

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

    def create(self):
        print 'creating %s name:%s' % (self.t['Type'], self.name)

        self.stack.resolve_attributes(self.t)
        self.stack.resolve_joins(self.t)
        self.stack.resolve_base64(self.t)

    def instance_id_set(self, inst):
        self.instance_id = inst

    def state_set(self, new_state, reason="state changed"):
        if new_state is self.CREATE_COMPLETE:
            try:
                rs = {}
                rs['state'] = new_state
                rs['stack_id'] = self.stack.id
                rs['nova_instance'] = self.instance_id
                rs['name'] = self.name
                rs['stack_name'] = self.stack.name
                new_rs = db_api.resource_create(None, rs)
                self.id = new_rs.id

            except Exception as ex:
                print 'db error %s' % str(ex)

        if new_state != self.state:
            ev = {}
            ev['logical_resource_id'] = self.name
            ev['physical_resource_id'] = self.name
            ev['stack_id'] = self.stack.id
            ev['stack_name'] = self.stack.name
            ev['resource_status'] = new_state
            ev['name'] = new_state
            ev['resource_status_reason'] = reason
            ev['resource_type'] = self.t['Type']
            ev['resource_properties'] = self.t['Properties']
            try:
                db_api.event_create(None, ev)
            except Exception as ex:
                print 'db error %s' % str(ex)
            self.state = new_state

    def delete(self):
        print 'deleting %s name:%s inst:%s db_id:%s' % (self.t['Type'], self.name,
                                                     self.instance_id, str(self.id))

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

    def create(self):
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(GenericResource, self).create()
        print 'creating GenericResource %s' % self.name
        self.state_set(self.CREATE_COMPLETE)

class SecurityGroup(Resource):

    def __init__(self, name, json_snippet, stack):
        super(SecurityGroup, self).__init__(name, json_snippet, stack)
        self.instance_id = ''

        if self.t['Properties'].has_key('GroupDescription'):
            self.description = self.t['Properties']['GroupDescription']
        else:
            self.description = ''

    def create(self):
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        Resource.create(self)

        sec = self.nova().security_groups.create(self.name, self.description)
        self.instance_id_set(sec.id)

        if self.t['Properties'].has_key('SecurityGroupIngress'):
            for i in self.t['Properties']['SecurityGroupIngress']:
                rule = self.nova().security_group_rules.create(sec.id,
                                                               i['IpProtocol'],
                                                               i['FromPort'],
                                                               i['ToPort'],
                                                               i['CidrIp'])
        self.state_set(self.CREATE_COMPLETE)

    def delete(self):
        if self.state == self.DELETE_IN_PROGRESS or self.state == self.DELETE_COMPLETE:
            return

        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)

        if self.instance_id != None:
            sec = self.nova().security_groups.get(self.instance_id)

            for rule in sec.rules:
                self.nova().security_group_rules.delete(rule['id'])

            self.nova().security_groups.delete(sec)
            self.instance_id = None

        self.state_set(self.DELETE_COMPLETE)

    def FnGetRefId(self):
        return unicode(self.name)

class ElasticIp(Resource):
    def __init__(self, name, json_snippet, stack):
        super(ElasticIp, self).__init__(name, json_snippet, stack)
        self.instance_id = ''
        self.ipaddress = ''

        if self.t.has_key('Properties') and self.t['Properties'].has_key('Domain'):
            logger.warn('*** can\'t support Domain %s yet' % (self.t['Properties']['Domain']))

    def create(self):
        """Allocate a floating IP for the current tenant."""
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(ElasticIp, self).create()

        ips = self.nova().floating_ips.create()
        print 'ElasticIp create %s' % str(ips)
        self.ipaddress = ips.ip
        self.instance_id_set(ips.id)
        self.state_set(self.CREATE_COMPLETE)

    def delete(self):
        """De-allocate a floating IP."""
        if self.state == self.DELETE_IN_PROGRESS or self.state == self.DELETE_COMPLETE:
            return

        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)

        if self.instance_id != None:
            self.nova().floating_ips.delete(self.instance_id)

        self.state_set(self.DELETE_COMPLETE)

    def FnGetRefId(self):
        return unicode(self.ipaddress)

    def FnGetAtt(self, key):
        if key == 'AllocationId':
            return unicode(self.instance_id)
        else:
            logger.warn('%s.GetAtt(%s) is not handled' % (self.name, key))
            return unicode('')

class ElasticIpAssociation(Resource):
    def __init__(self, name, json_snippet, stack):
        super(ElasticIpAssociation, self).__init__(name, json_snippet, stack)

    def FnGetRefId(self):
        if not self.t['Properties'].has_key('EIP'):
            return unicode('0.0.0.0')
        else:
            return unicode(self.t['Properties']['EIP'])

    def create(self):
        """Add a floating IP address to a server."""

        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(ElasticIpAssociation, self).create()
        print 'ElasticIpAssociation %s.add_floating_ip(%s)' % (self.t['Properties']['InstanceId'],
                                                               self.t['Properties']['EIP'])

        server = self.nova().servers.get(self.t['Properties']['InstanceId'])
        server.add_floating_ip(self.t['Properties']['EIP'])
        self.instance_id_set(self.t['Properties']['EIP'])
        self.state_set(self.CREATE_COMPLETE)

    def delete(self):
        """Remove a floating IP address from a server."""
        if self.state == self.DELETE_IN_PROGRESS or self.state == self.DELETE_COMPLETE:
            return

        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)

        server = self.nova().servers.get(self.t['Properties']['InstanceId'])
        server.remove_floating_ip(self.t['Properties']['EIP'])

        self.state_set(self.DELETE_COMPLETE)


class Volume(Resource):
    def __init__(self, name, json_snippet, stack):
        super(Volume, self).__init__(name, json_snippet, stack)

    def create(self):
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(Volume, self).create()

        vol = self.nova('volume').volumes.create(self.t['Properties']['Size'],
                                                 display_name=self.name,
                                                 display_description=self.name)

        while vol.status == 'creating':
            eventlet.sleep(1)
            vol.get()
        if vol.status == 'available':
            self.instance_id_set(vol.id)
            self.state_set(self.CREATE_COMPLETE)
        else:
            self.state_set(self.CREATE_FAILED)

    def delete(self):
        if self.state == self.DELETE_IN_PROGRESS or self.state == self.DELETE_COMPLETE:
            return

        if self.instance_id != None:
            vol = self.nova('volume').volumes.get(self.instance_id)
            if vol.status == 'in-use':
                print 'cant delete volume when in-use'
                return

        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)

        if self.instance_id != None:
            self.nova('volume').volumes.delete(self.instance_id)
        self.state_set(self.DELETE_COMPLETE)

class VolumeAttachment(Resource):
    def __init__(self, name, json_snippet, stack):
        super(VolumeAttachment, self).__init__(name, json_snippet, stack)

    def create(self):

        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(VolumeAttachment, self).create()

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
            self.instance_id_set(va.id)
            self.state_set(self.CREATE_COMPLETE)
        else:
            self.state_set(self.CREATE_FAILED)

    def delete(self):
        if self.state == self.DELETE_IN_PROGRESS or self.state == self.DELETE_COMPLETE:
            return
        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)

        print 'VolumeAttachment un-attaching %s %s' % (self.t['Properties']['InstanceId'],
                                                       self.instance_id)

        self.nova().volumes.delete_server_volume(self.t['Properties']['InstanceId'],
                                                 self.instance_id)

        vol = self.nova('volume').volumes.get(self.t['Properties']['VolumeId'])
        while vol.status == 'in-use':
            print 'trying to un-attach %s, but still %s' % (self.instance_id, vol.status)
            eventlet.sleep(1)
            try:
                self.nova().volumes.delete_server_volume(self.t['Properties']['InstanceId'],
                                                         self.instance_id)
            except Exception:
                pass
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

        props = self.t['Properties']
        if not props.has_key('KeyName'):
            raise exception.UserParameterMissing(key='KeyName')
        if not props.has_key('InstanceType'):
            raise exception.UserParameterMissing(key='InstanceType')
        if not props.has_key('ImageId'):
            raise exception.UserParameterMissing(key='ImageId')

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
                    #print 'service create %s_%s' % (self.name, s)
        except KeyError as e:
            # if there is no config then no services.
            pass

        # TODO(sdake)
        # heat API should take care of these conversions and feed them into
        # heat engine in an openstack specific json format

        flavor = self.itype_oflavor[self.t['Properties']['InstanceType']]
        distro_name = self.stack.parameter_get('LinuxDistribution')
        key_name = self.t['Properties']['KeyName']

        keypairs = self.nova().keypairs.list()
        key_exists = False
        for k in keypairs:
            if k.name == key_name:
                # cool it exists
                key_exists = True
                break
        if not key_exists:
            raise exception.UserKeyPairMissing(key_name=key_name)

        image_name = self.t['Properties']['ImageId']
        image_id = None
        image_list = self.nova().images.list()
        for o in image_list:
            if o.name == image_name:
                image_id = o.id

        if image_id is None:
            print "Image %s was not found in glance" % image_name
            raise exception.ImageNotFound(image_name=image_name)

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
            self.instance_id_set(server.id)
            self.state_set(self.CREATE_COMPLETE)
            # just record the first ipaddress
            for n in server.networks:
                self.ipaddress = server.networks[n][0]
                break
        else:
            self.state_set(self.CREATE_FAILED)

    def delete(self):
        if self.state == self.DELETE_IN_PROGRESS or self.state == self.DELETE_COMPLETE:
            return
        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)
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
