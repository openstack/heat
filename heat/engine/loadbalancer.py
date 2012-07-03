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

import urllib2
import json
import logging

from heat.common import exception
from heat.engine.resources import Resource
from heat.db import api as db_api
from heat.engine import parser
from novaclient.exceptions import NotFound

logger = logging.getLogger(__file__)

lb_template = '''
{
  "AWSTemplateFormatVersion": "2010-09-09",
  "Description": "Built in HAProxy server",
  "Parameters" : {
    "KeyName" : {
      "Type" : "String"
    }
  },
  "Resources": {
    "LoadBalancerInstance": {
      "Type": "AWS::EC2::Instance",
      "Metadata": {
        "AWS::CloudFormation::Init": {
          "config": {
            "packages": {
              "yum": {
                "haproxy"        : []
              }
            },
            "services": {
              "systemd": {
                "haproxy"   : { "enabled": "true", "ensureRunning": "true" }
              }
            },
            "files": {
              "/etc/haproxy/haproxy.cfg": {
                "content": ""},
                "mode": "000644",
                "owner": "root",
                "group": "root"
            }
          }
        }
      },
      "Properties": {
        "ImageId": "F16-x86_64-cfntools",
        "InstanceType": "m1.small",
        "KeyName": { "Ref": "KeyName" },
        "UserData": { "Fn::Base64": { "Fn::Join": ["", [
          "#!/bin/bash -v\\n",
          "/opt/aws/bin/cfn-init -s ",
          { "Ref": "AWS::StackName" },
          "    --region ", { "Ref": "AWS::Region" }, "\\n"
        ]]}}
      }
    }
  },

  "Outputs": {
    "PublicIp": {
      "Value": { "Fn::GetAtt": [ "LoadBalancerInstance", "PublicIp" ] },
      "Description": "instance IP"
    }
  }
}
'''


#
# TODO(asalkeld) once we have done a couple of these composite
# Resources we should probably make a generic CompositeResource class.
# There will be plenty of scope for it. I resisted doing this initially
# to see how what the other composites require.
#
# Also the above inline template _could_ be placed in an external file
# at the moment this is because we will probably need to implement a
# LoadBalancer based on keepalived as well (for for ssl support).
#
class LoadBalancer(Resource):

    listeners_schema = {
        'InstancePort': {'Type': 'Integer',
                         'Required': True},
        'LoadBalancerPort': {'Type': 'Integer',
                             'Required': True},
        'Protocol': {'Type': 'String',
                     'Required': True,
                     'AllowedValues': ['TCP', 'HTTP']},
        'SSLCertificateId': {'Type': 'String',
                             'Implemented': False},
        'PolicyNames': {'Type': 'Map',
                        'Implemented': False}
    }
    healthcheck_schema = {
        'HealthyThreshold': {'Type': 'Integer',
                             'Required': True},
        'Interval': {'Type': 'Integer',
                     'Required': True},
        'Target': {'Type': 'String',
                   'Required': True},
        'Timeout': {'Type': 'Integer',
                    'Required': True},
        'UnHealthyTheshold': {'Type': 'Integer',
                              'Required': True},
    }

    properties_schema = {
        'AvailabilityZones': {'Type': 'List',
                              'Required': True},
        'HealthCheck': {'Type': 'Map',
                        'Implemented': False,
                        'Schema': healthcheck_schema},
        'Instances': {'Type': 'List'},
        'Listeners': {'Type': 'List',
                      'Schema': listeners_schema},
        'AppCookieStickinessPolicy': {'Type': 'String',
                                      'Implemented': False},
        'LBCookieStickinessPolicy': {'Type': 'String',
                                     'Implemented': False},
        'SecurityGroups': {'Type': 'String',
                           'Implemented': False},
        'Subnets': {'Type': 'List',
                    'Implemented': False}
    }

    def __init__(self, name, json_snippet, stack):
        Resource.__init__(self, name, json_snippet, stack)
        self._nested = None

    def _params(self):
        # total hack - probably need an admin key here.
        params = {'KeyName': {'Ref': 'KeyName'}}
        p = self.stack.resolve_static_data(params)
        return p

    def nested(self):
        if self._nested is None:
            if self.instance_id is None:
                return None

            st = db_api.stack_get(self.stack.context, self.instance_id)
            if not st:
                raise exception.NotFound('Nested stack not found in DB')

            n = parser.Stack(self.stack.context, st.name,
                             st.raw_template.parsed_template.template,
                             self.instance_id, self._params())
            self._nested = n

        return self._nested

    def _instance_to_ipaddress(self, inst):
        '''
        Return the server's IP address, fetching it from Nova
        '''
        try:
            server = self.nova().servers.get(inst)
        except NotFound as ex:
            logger.warn('Instance IP address not found (%s)' % str(ex))
        else:
            for n in server.networks:
                return server.networks[n][0]

        return '0.0.0.0'

    def _haproxy_config(self, templ):
        # initial simplifications:
        # - only one Listener
        # - static (only use Instances)
        # - only http (no tcp or ssl)
        #
        # option httpchk HEAD /check.txt HTTP/1.0
        gl = '''
    global
        daemon
        maxconn 256

    defaults
        mode http
        timeout connect 5000ms
        timeout client 50000ms
        timeout server 50000ms
'''

        listener = self.properties['Listeners'][0]
        lb_port = listener['LoadBalancerPort']
        inst_port = listener['InstancePort']
        spaces = '            '
        frontend = '''
        frontend http
            bind *:%s
''' % (lb_port)

        backend = '''
        default_backend servers

        backend servers
            balance roundrobin
            option http-server-close
            option forwardfor
'''
        servers = []
        n = 1
        for i in self.properties['Instances']:
            ip = self._instance_to_ipaddress(i)
            servers.append('%sserver server%d %s:%s' % (spaces, n,
                                                        ip, inst_port))
            n = n + 1

        return '%s%s%s%s\n' % (gl, frontend, backend, '\n'.join(servers))

    def handle_create(self):
        templ = json.loads(lb_template)

        md = templ['Resources']['LoadBalancerInstance']['Metadata']
        files = md['AWS::CloudFormation::Init']['config']['files']
        cfg = self._haproxy_config(templ)
        files['/etc/haproxy/haproxy.cfg']['content'] = cfg

        self._nested = parser.Stack(self.stack.context,
                                    self.name,
                                    templ,
                                    parms=self._params(),
                                    metadata_server=self.stack.metadata_server)

        rt = {'template': templ, 'stack_name': self.name}
        new_rt = db_api.raw_template_create(None, rt)

        parent_stack = db_api.stack_get(self.stack.context, self.stack.id)

        s = {'name': self.name,
             'owner_id': self.stack.id,
             'raw_template_id': new_rt.id,
             'user_creds_id': parent_stack.user_creds_id,
             'username': self.stack.context.username}
        new_s = db_api.stack_create(None, s)
        self._nested.id = new_s.id

        pt = {'template': self._nested.t, 'raw_template_id': new_rt.id}
        new_pt = db_api.parsed_template_create(None, pt)

        self._nested.parsed_template_id = new_pt.id

        self._nested.create()
        self.instance_id_set(self._nested.id)

    def handle_delete(self):
        try:
            stack = self.nested()
        except exception.NotFound:
            logger.info("Stack not found to delete")
        else:
            if stack is not None:
                stack.delete()

    def FnGetAtt(self, key):
        '''
        We don't really support any of these yet.
        '''
        allow = ('CanonicalHostedZoneName',
                 'CanonicalHostedZoneNameID',
                 'DNSName',
                 'SourceSecurityGroupName',
                 'SourceSecurityGroupOwnerAlias')

        if not key in allow:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        stack = self.nested()
        if stack is None:
            # This seems like a hack, to get past validation
            return ''
        if key == 'DNSName':
            return stack.output('PublicIp')
        else:
            return ''
