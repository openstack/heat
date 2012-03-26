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

from heat.engine import simpledb

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

        stack.resolve_static_refs(self.t)
        stack.resolve_find_in_map(self.t)

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

            simpledb.event_append(ev)
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
        # TODO start the volume here
        # of size -> self.t['Properties']['Size']
        # and set self.instance_id to the volume id
        logger.info('$ euca-create-volume -s %s -z nova' % self.t['Properties']['Size'])
        self.instance_id = 'vol-4509854'

class VolumeAttachment(Resource):
    def __init__(self, name, json_snippet, stack):
        super(VolumeAttachment, self).__init__(name, json_snippet, stack)

    def start(self):

        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(VolumeAttachment, self).start()
        # TODO attach the volume with an id of:
        # self.t['Properties']['VolumeId']
        # to the vm of instance:
        # self.t['Properties']['InstanceId']
        # and make sure that the mountpoint is:
        # self.t['Properties']['Device']
        logger.info('$ euca-attach-volume %s -i %s -d %s' % (self.t['Properties']['VolumeId'],
                                                             self.t['Properties']['InstanceId'],
                                                             self.t['Properties']['Device']))

class Instance(Resource):

    def __init__(self, name, json_snippet, stack):
        super(Instance, self).__init__(name, json_snippet, stack)

        if not self.t['Properties'].has_key('AvailabilityZone'):
            self.t['Properties']['AvailabilityZone'] = 'nova'
        self.itype_oflavor = {'t1.micro': 'm1.tiny',
            'm1.small': 'm1.small',
            'm1.medium': 'm1.medium',
            'm1.large': 'm1.large',
            'm2.xlarge': 'm1.large',
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

                print '----------------------'
                try:
                    print '\n'.join(new_script)
                except:
                    print str(new_script)
                    raise
                print '----------------------'

        try:
            con = self.t['Metadata']["AWS::CloudFormation::Init"]['config']
            for st in con['services']:
                for s in con['services'][st]:
                    print 'service start %s_%s' % (self.name, s)
        except KeyError as e:
            # if there is no config then no services.
            pass


        # TODO start the instance here.
        # and set self.instance_id
        logger.info('$ euca-run-instances -k %s -t %s %s' % (self.t['Properties']['KeyName'],
                                                             self.t['Properties']['InstanceType'],
                                                             self.t['Properties']['ImageId']))

        # Convert AWS instance type to OpenStack flavor
        # TODO(sdake)
        # heat API should take care of these conversions and feed them into
        # heat engine in an openstack specific json format
        flavor = self.itype_oflavor[self.t['Properties']['InstanceType']]
        self.instance_id = 'i-734509008'

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
