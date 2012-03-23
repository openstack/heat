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

import json
import logging

logger = logging.getLogger('heat.engine.parser')

parse_debug = False
#parse_debug = True


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
        self.state = self.CREATE_IN_PROGRESS
        super(GenericResource, self).start()
        print 'Starting GenericResource %s' % self.name


class ElasticIp(Resource):
    def __init__(self, name, json_snippet, stack):
        super(ElasticIp, self).__init__(name, json_snippet, stack)
        self.instance_id = ''

        if self.t.has_key('Properties') and self.t['Properties'].has_key('Domain'):
            print '*** can\'t support Domain %s yet' % (self.t['Properties']['Domain'])

    def start(self):
        if self.state != None:
            return
        self.state = Resource.CREATE_IN_PROGRESS
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
            print '*** can\'t support this yet'
        if self.t['Properties'].has_key('AllocationId'):
            print '*** can\'t support AllocationId %s yet' % (self.t['Properties']['AllocationId'])

    def FnGetRefId(self):
        if not self.t['Properties'].has_key('EIP'):
            return unicode('0.0.0.0')
        else:
            return unicode(self.t['Properties']['EIP'])

    def start(self):

        if self.state != None:
            return
        self.state = Resource.CREATE_IN_PROGRESS
        super(ElasticIpAssociation, self).start()
        print '$ euca-associate-address -i %s %s' % (self.t['Properties']['InstanceId'],
                                                     self.t['Properties']['EIP'])

class Volume(Resource):
    def __init__(self, name, json_snippet, stack):
        super(Volume, self).__init__(name, json_snippet, stack)

    def start(self):

        if self.state != None:
            return
        self.state = Resource.CREATE_IN_PROGRESS
        super(Volume, self).start()
        # TODO start the volume here
        # of size -> self.t['Properties']['Size']
        # and set self.instance_id to the volume id
        print '$ euca-create-volume -s %s -z nova' % self.t['Properties']['Size']
        self.instance_id = 'vol-4509854'

class VolumeAttachment(Resource):
    def __init__(self, name, json_snippet, stack):
        super(VolumeAttachment, self).__init__(name, json_snippet, stack)

    def start(self):

        if self.state != None:
            return
        self.state = Resource.CREATE_IN_PROGRESS
        super(VolumeAttachment, self).start()
        # TODO attach the volume with an id of:
        # self.t['Properties']['VolumeId']
        # to the vm of instance:
        # self.t['Properties']['InstanceId']
        # and make sure that the mountpoint is:
        # self.t['Properties']['Device']
        print '$ euca-attach-volume %s -i %s -d %s' % (self.t['Properties']['VolumeId'],
                                                       self.t['Properties']['InstanceId'],
                                                       self.t['Properties']['Device'])

class Instance(Resource):

    def __init__(self, name, json_snippet, stack):
        super(Instance, self).__init__(name, json_snippet, stack)

        if not self.t['Properties'].has_key('AvailabilityZone'):
            self.t['Properties']['AvailabilityZone'] = 'nova'

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
        self.state = Resource.CREATE_IN_PROGRESS
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

                if parse_debug:
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
        print '$ euca-run-instances -k %s -t %s %s' % (self.t['Properties']['KeyName'],
                                                       self.t['Properties']['InstanceType'],
                                                       self.t['Properties']['ImageId'])
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

class Stack:
    def __init__(self, template, stack_name):

        self.t = template
        if self.t.has_key('Parameters'):
            self.parms = self.t['Parameters']
        else:
            self.parms = {}
        if self.t.has_key('Mappings'):
            self.maps = self.t['Mappings']
        else:
            self.maps = {}
        self.res = {}
        self.doc = None
        self.name = stack_name

        self.parms['AWS::Region'] = {"Description" : "AWS Regions", "Type" : "String", "Default" : "ap-southeast-1",
              "AllowedValues" : ["us-east-1","us-west-1","us-west-2","sa-east-1","eu-west-1","ap-southeast-1","ap-northeast-1"],
              "ConstraintDescription" : "must be a valid EC2 instance type." }

        self.resources = {}
        for r in self.t['Resources']:
            type = self.t['Resources'][r]['Type']
            if type == 'AWS::EC2::Instance':
                self.resources[r] = Instance(r, self.t['Resources'][r], self)
            elif type == 'AWS::EC2::Volume':
                self.resources[r] = Volume(r, self.t['Resources'][r], self)
            elif type == 'AWS::EC2::VolumeAttachment':
                self.resources[r] = VolumeAttachment(r, self.t['Resources'][r], self)
            elif type == 'AWS::EC2::EIP':
                self.resources[r] = ElasticIp(r, self.t['Resources'][r], self)
            elif type == 'AWS::EC2::EIPAssociation':
                self.resources[r] = ElasticIpAssociation(r, self.t['Resources'][r], self)
            else:
                self.resources[r] = GenericResource(r, self.t['Resources'][r], self)

            self.calulate_dependancies(self.t['Resources'][r], self.resources[r])
        #print json.dumps(self.t['Resources'], indent=2)
        if parse_debug:
            for r in self.t['Resources']:
                print '%s -> %s' % (r, self.resources[r].depends_on)

    def start(self):
        # start Volumes first.
        for r in self.t['Resources']:
            if self.t['Resources'][r]['Type'] == 'AWS::EC2::Volume':
                self.resources[r].start()

        for r in self.t['Resources']:
            #print 'calling start [stack->%s]' % (self.resources[r].name)
            self.resources[r].start()

    def calulate_dependancies(self, s, r):
        if isinstance(s, dict):
            for i in s:
                if i == 'Fn::GetAtt':
                    #print '%s seems to depend on %s' % (r.name, s[i][0])
                    #r.depends_on.append(s[i][0])
                    pass
                elif i == 'Ref':
                    #print '%s Refences %s' % (r.name, s[i])
                    r.depends_on.append(s[i])
                elif i == 'DependsOn' or i == 'Ref':
                    #print '%s DependsOn on %s' % (r.name, s[i])
                    r.depends_on.append(s[i])
                else:
                    self.calulate_dependancies(s[i], r)
        elif isinstance(s, list):
            for index, item in enumerate(s):
                self.calulate_dependancies(item, r)

    def parameter_get(self, key):
        if self.parms[key] == None:
            #print 'None Ref: %s' % key
            return '=EMPTY='
        elif self.parms[key].has_key('Value'):
            return self.parms[key]['Value']
        elif self.parms[key].has_key('Default'):
            return self.parms[key]['Default']
        else:
            #print 'Missing Ref: %s' % key
            return '=EMPTY='


    def resolve_static_refs(self, s):
        '''
            looking for { "Ref": "str" }
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Ref' and \
                      isinstance(s[i], (basestring, unicode)) and \
                      self.parms.has_key(s[i]):
                    return self.parameter_get(s[i])
                else:
                    s[i] = self.resolve_static_refs(s[i])
        elif isinstance(s, list):
            for index, item in enumerate(s):
                #print 'resolve_static_refs %d %s' % (index, item)
                s[index] = self.resolve_static_refs(item)
        return s

    def resolve_find_in_map(self, s):
        '''
            looking for { "Fn::FindInMap": ["str", "str"] }
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Fn::FindInMap':
                    obj = self.maps
                    if isinstance(s[i], list):
                        #print 'map list: %s' % s[i]
                        for index, item in enumerate(s[i]):
                            if isinstance(item, dict):
                                item = self.resolve_find_in_map(item)
                                #print 'map item dict: %s' % (item)
                            else:
                                pass
                                #print 'map item str: %s' % (item)
                            obj = obj[item]
                    else:
                        obj = obj[s[i]]
                    return obj
                else:
                    s[i] = self.resolve_find_in_map(s[i])
        elif isinstance(s, list):
            for index, item in enumerate(s):
                s[index] = self.resolve_find_in_map(item)
        return s

    def resolve_attributes(self, s):
        '''
            looking for something like:
            {"Fn::GetAtt" : ["DBInstance", "Endpoint.Address"]}
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Ref' and self.resources.has_key(s[i]):
                    return self.resources[s[i]].FnGetRefId()
                elif i == 'Fn::GetAtt':
                    resource_name = s[i][0]
                    key_name = s[i][1]
                    return self.resources[resource_name].FnGetAtt(key_name)
                else:
                    s[i] = self.resolve_attributes(s[i])
        elif isinstance(s, list):
            for index, item in enumerate(s):
                s[index] = self.resolve_attributes(item)
        return s

    def resolve_joins(self, s):
        '''
            looking for { "Fn::join": [] }
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Fn::Join':
                    j = None
                    try:
                        j = s[i][0].join(s[i][1])
                    except:
                        print '*** could not join %s' % s[i]
                    return j
                else:
                    s[i] = self.resolve_joins(s[i])
        elif isinstance(s, list):
            for index, item in enumerate(s):
                s[index] = self.resolve_joins(item)
        return s

    def resolve_base64(self, s):
        '''
            looking for { "Fn::join": [] }
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Fn::Base64':
                    return s[i]
                else:
                    s[i] = self.resolve_base64(s[i])
        elif isinstance(s, list):
            for index, item in enumerate(s):
                s[index] = self.resolve_base64(item)
        return s


