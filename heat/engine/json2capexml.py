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
import libxml2
import logging

from heat.common import utils

logger = logging.getLogger('heat.engine.json2capexml')

class Json2CapeXml:
    def __init__(self, template, stack_name):

        self.t = template
        self.parms = self.t['Parameters']
        self.maps = self.t['Mappings']
        self.res = {}
        self.doc = None
        self.name = stack_name

        self.parms['AWS::Region'] = {"Description" : "AWS Regions", "Type" : "String", "Default" : "ap-southeast-1",
              "AllowedValues" : ["us-east-1","us-west-1","us-west-2","sa-east-1","eu-west-1","ap-southeast-1","ap-northeast-1"],
              "ConstraintDescription" : "must be a valid EC2 instance type." }

        # expected user parameters
        self.parms['AWS::StackName'] = {'Default': stack_name}
        self.parms['KeyName'] = {'Default': 'harry-45-5-34-5'}

        for r in self.t['Resources']:
            # fake resource instance references
            self.parms[r] = {'Default': utils.generate_uuid()}

        self.resolve_static_refs(self.t['Resources'])
        self.resolve_find_in_map(self.t['Resources'])
        #self.resolve_attributes(self.t['Resources'])
        self.resolve_joins(self.t['Resources'])
        self.resolve_base64(self.t['Resources'])
        #print json.dumps(self.t['Resources'], indent=2)


    def convert(self):

        self.doc = libxml2.newDoc("1.0")
        dep = self.doc.newChild(None, "deployable", None)
        dep.setProp("name", self.name)
        dep.setProp("uuid", 'bogus')
        dep.setProp("username", 'nobody-yet')
        n_asses = dep.newChild(None, "assemblies", None)

        for r in self.t['Resources']:
            type = self.t['Resources'][r]['Type']
            if type != 'AWS::EC2::Instance':
                print 'ignoring Resource %s (%s)' % (r, type)
                continue

            n_ass = n_asses.newChild(None, 'assembly', None)
            n_ass.setProp("name", r)
            n_ass.setProp("uuid", self.parms[r]['Default'])
            props = self.t['Resources'][r]['Properties']
            for p in props:
                if p == 'ImageId':
                    n_ass.setProp("image_name", props[p])
                elif p == 'UserData':
                    new_script = []
                    script_lines = props[p].split('\n')
                    for l in script_lines:
                        if '#!/' in l:
                            new_script.append(l)
                            self.insert_package_and_services(self.t['Resources'][r], new_script)
                        else:
                            new_script.append(l)

                    startup = n_ass.newChild(None, 'startup', '\n'.join(new_script))


            try:
                con = self.t['Resources'][r]['Metadata']["AWS::CloudFormation::Init"]['config']
                n_services = n_ass.newChild(None, 'services', None)
                for st in con['services']:
                    for s in con['services'][st]:
                        n_service = n_services.newChild(None, 'service', None)
                        n_service.setProp("name", '%s_%s' % (r, s))
                        n_service.setProp("type", s)
                        n_service.setProp("provider", 'pacemaker')
                        n_service.setProp("class", 'lsb')
                        n_service.setProp("monitor_interval", '30s')
                        n_service.setProp("escalation_period", '1000')
                        n_service.setProp("escalation_failures", '3')
            except KeyError as e:
                # if there is no config then no services.
                pass

    def get_xml(self):
        str = self.doc.serialize(None, 1)
        self.doc.freeDoc()
        self.doc = None
        return str

    def convert_and_write(self):
        self.convert()
        try:
            filename = '/var/run/%s.xml' % self.name
            open(filename, 'w').write(self.doc.serialize(None, 1))
            self.doc.freeDoc()
            self.doc = None
        except IOError as e:
            logger.error('couldn\'t write to /var/run/ error %s' % e)

    def insert_package_and_services(self, r, new_script):

        try:
            con = r['Metadata']["AWS::CloudFormation::Init"]['config']
        except KeyError as e:
            return

        for pt in con['packages']:
            if pt == 'yum':
                for p in con['packages']['yum']:
                    new_script.append('yum install -y %s' % p)
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
                    v = con['services']['systemd'][s]
                    if v['enabled'] == 'true':
                        new_script.append('chkconfig %s on' % s)
                    if v['ensureRunning'] == 'true':
                        new_script.append('/etc/init.d/start %s' % s)

    def resolve_static_refs(self, s):
        '''
            looking for { "Ref": "str" }
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Ref' and isinstance(s[i], (basestring, unicode)) and \
                      self.parms.has_key(s[i]):
                    if self.parms[s[i]] == None:
                        print 'None Ref: %s' % str(s[i])
                    elif self.parms[s[i]].has_key('Default'):
                        # note the "ref: values" are in a dict of
                        # size one, so return is fine.
                        #print 'Ref: %s == %s' % (s[i], self.parms[s[i]]['Default'])
                        return self.parms[s[i]]['Default']
                    else:
                        print 'missing Ref: %s' % str(s[i])
                else:
                    s[i] = self.resolve_static_refs(s[i])
        elif isinstance(s, list):
            for index, item in enumerate(s):
                #print 'resolve_static_refs %d %s' % (index, item)
                s[index] = self.resolve_static_refs(item)
        return s

    def resolve_find_in_map(self, s):
        '''
            looking for { "Ref": "str" }
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


    def resolve_joins(self, s):
        '''
            looking for { "Fn::join": [] }
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Fn::Join':
                    return s[i][0].join(s[i][1])
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


