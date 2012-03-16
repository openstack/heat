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

"""
/stack endpoint for heat v1 API
"""
import dbus
import errno
import eventlet
from eventlet.green import socket
import fcntl
import httplib
import json
import libxml2
import logging
import os
import stat
import sys
import urlparse

import webob
from webob.exc import (HTTPNotFound,
                       HTTPConflict,
                       HTTPBadRequest)

from heat.common import exception
from heat.common import utils
from heat.common import wsgi

logger = logging.getLogger('heat.api.v1.stacks')

stack_db = {}


class Json2CapeXml:
    def __init__(self, template, stack_name):

        self.t = template
        self.parms = self.t['Parameters']
        self.maps = self.t['Mappings']
        self.res = {}

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


    def convert_and_write(self):

        name = self.parms['AWS::StackName']['Default']

        doc = libxml2.newDoc("1.0")
        dep = doc.newChild(None, "deployable", None)
        dep.setProp("name", name)
        dep.setProp("uuid", 'bogus')
        dep.setProp("monitor", 'active')
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

        try:
            filename = '/var/run/%s.xml' % name
            open(filename, 'w').write(doc.serialize(None, 1))
            doc.freeDoc()
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

def systemctl(method, name, instance=None):

    bus = dbus.SystemBus()

    sysd = bus.get_object('org.freedesktop.systemd1',
                         '/org/freedesktop/systemd1')

    actual_method = ''
    if method == 'start':
        actual_method = 'StartUnit'
    elif method == 'stop':
        actual_method = 'StopUnit'
    else:
        raise

    m = sysd.get_dbus_method(actual_method, 'org.freedesktop.systemd1.Manager')

    if instance == None:
        service = '%s.service' % (name)
    else:
        service = '%s@%s.service' % (name, instance)

    try:
        result = m(service, 'replace')
    except dbus.DBusException as e:
        logger.error('couldn\'t %s %s error: %s' % (method, name, e))
        return None
    return result


class CapeEventListener:

    def __init__(self):
        self.backlog = 50
        self.file = 'pacemaker-cloud-cped'

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        flags = fcntl.fcntl(sock, fcntl.F_GETFD)
        fcntl.fcntl(sock, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            st = os.stat(self.file)
        except OSError, err:
            if err.errno != errno.ENOENT:
                raise
        else:
            if stat.S_ISSOCK(st.st_mode):
                os.remove(self.file)
            else:
                raise ValueError("File %s exists and is not a socket", self.file)
        sock.bind(self.file)
        sock.listen(self.backlog)
        os.chmod(self.file, 0600)

        eventlet.spawn_n(self.cape_event_listner, sock)

    def cape_event_listner(self, sock):
        eventlet.serve(sock, self.cape_event_handle)

    def cape_event_handle(self, sock, client_addr):
        while True:
            x = sock.recv(4096)
            # TODO(asalkeld) format this event "nicely"
            logger.info('%s' % x.strip('\n'))
            if not x: break


class StackController(object):

    """
    WSGI controller for stacks resource in heat v1 API

    """

    def __init__(self, options):
        self.options = options
        self.stack_id = 1
        self.event_listener = CapeEventListener()

    def list(self, req):
        """
        Returns the following information for all stacks:
        """
        res = {'ListStacksResponse': {'ListStacksResult': {'StackSummaries': [] } } }
        summaries = res['ListStacksResponse']['ListStacksResult']['StackSummaries']
        for s in stack_db:
            mem = {}
            mem['StackId'] = stack_db[s]['StackId']
            mem['StackName'] = s
            mem['CreationTime'] = 'now'
            try:
                mem['TemplateDescription'] = stack_db[s]['Description']
                mem['StackStatus'] = stack_db[s]['StackStatus']
            except:
                mem['TemplateDescription'] = 'No description'
                mem['StackStatus'] = 'unknown'
            summaries.append(mem)

        return res

    def describe(self, req):

        stack_name = None
        if req.params.has_key('StackName'):
            stack_name = req.params['StackName']
            if not stack_db.has_key(stack_name):
                msg = _("Stack does not exist with that name.")
                return webob.exc.HTTPNotFound(msg)

        res = {'DescribeStacksResult': {'Stacks': [] } }
        summaries = res['DescribeStacksResult']['Stacks']
        for s in stack_db:
            if stack_name is None or s == stack_name:
                mem = {}
                mem['StackId'] = stack_db[s]['StackId']
                mem['StackStatus'] = stack_db[s]['StackStatus']
                mem['StackName'] = s
                mem['CreationTime'] = 'now'
                mem['DisableRollback'] = 'false'
                mem['Outputs'] = '[]'
                summaries.append(mem)

        return res

    def _get_template(self, req):
        if req.params.has_key('TemplateBody'):
            logger.info('TemplateBody ...')
            return req.params['TemplateBody']
        elif req.params.has_key('TemplateUrl'):
            logger.info('TemplateUrl %s' % req.params['TemplateUrl'])
            url = urlparse.urlparse(req.params['TemplateUrl'])
            if url.scheme == 'https':
                conn = httplib.HTTPSConnection(url.netloc)
            else:
                conn = httplib.HTTPConnection(url.netloc)
            conn.request("GET", url.path)
            r1 = conn.getresponse()
            logger.info('status %d' % r1.status)
            if r1.status == 200:
                data = r1.read()
                conn.close()
            else:
                data = None
            return data

        return None

    def _apply_user_parameters(self, req, stack):
        # TODO
        pass

    def create(self, req):
        """
        :param req: The WSGI/Webob Request object

        :raises HttpBadRequest if not template is given
        :raises HttpConflict if object already exists
        """
        if stack_db.has_key(req.params['StackName']):
            msg = _("Stack already exists with that name.")
            return webob.exc.HTTPConflict(msg)

        templ = self._get_template(req)
        if templ is None:
            msg = _("TemplateBody or TemplateUrl were not given.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        stack = json.loads(templ)
        my_id = '%s-%d' % (req.params['StackName'], self.stack_id)
        self.stack_id = self.stack_id + 1
        stack['StackId'] = my_id
        stack['StackStatus'] = 'CREATE_COMPLETE'
        self._apply_user_parameters(req, stack)
        stack_db[req.params['StackName']] = stack

        cape_transformer = Json2CapeXml(stack, req.params['StackName'])
        cape_transformer.convert_and_write()

        systemctl('start', 'pcloud-cape-sshd', req.params['StackName'])

        return {'CreateStackResult': {'StackId': my_id}}

    def update(self, req):
        """
        :param req: The WSGI/Webob Request object

        :raises HttpNotFound if object is not available
        """
        if not stack_db.has_key(req.params['StackName']):
            msg = _("Stack does not exist with that name.")
            return webob.exc.HTTPNotFound(msg)

        stack = stack_db[req.params['StackName']]
        my_id = stack['StackId']
        templ = self._get_template(req)
        if templ:
            stack = json.loads(templ)
            stack['StackId'] = my_id
            stack_db[req.params['StackName']] = stack

        self._apply_user_parameters(req, stack)
        stack['StackStatus'] = 'UPDATE_COMPLETE'

        return {'UpdateStackResult': {'StackId': my_id}}


    def delete(self, req):
        """
        Deletes the object and all its resources

        :param req: The WSGI/Webob Request object

        :raises HttpBadRequest if the request is invalid
        :raises HttpNotFound if object is not available
        :raises HttpNotAuthorized if object is not
                deleteable by the requesting user
        """
        logger.info('in delete %s ' % req.params['StackName'])
        if not stack_db.has_key(req.params['StackName']):
            msg = _("Stack does not exist with that name.")
            return webob.exc.HTTPNotFound(msg)

        del stack_db[req.params['StackName']]

        systemctl('stop', 'pcloud-cape-sshd', req.params['StackName'])

def create_resource(options):
    """Stacks resource factory method"""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(StackController(options), deserializer, serializer)
