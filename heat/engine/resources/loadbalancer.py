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
import os

from oslo.config import cfg

from heat.common import exception
from heat.common import template_format
from heat.engine import stack_resource
from heat.engine.resources import nova_utils

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)

lb_template_default = r'''
{
  "AWSTemplateFormatVersion": "2010-09-09",
  "Description": "Built in HAProxy server",
  "Parameters" : {
    "KeyName" : {
      "Type" : "String"
    }
  },
  "Resources": {
    "latency_watcher": {
     "Type": "AWS::CloudWatch::Alarm",
     "Properties": {
        "MetricName": "Latency",
        "Namespace": "AWS/ELB",
        "Statistic": "Average",
        "Period": "60",
        "EvaluationPeriods": "1",
        "Threshold": "2",
        "AlarmActions": [],
        "ComparisonOperator": "GreaterThanThreshold"
      }
    },
    "CfnLBUser" : {
      "Type" : "AWS::IAM::User"
    },
    "CfnLBAccessKey" : {
      "Type" : "AWS::IAM::AccessKey",
      "Properties" : {
        "UserName" : {"Ref": "CfnLBUser"}
      }
    },
    "LB_instance": {
      "Type": "AWS::EC2::Instance",
      "Metadata": {
        "AWS::CloudFormation::Init": {
          "config": {
            "packages": {
              "yum": {
                "cronie"         : [],
                "haproxy"        : [],
                "socat"          : [],
                "python-psutil"  : []
              }
            },
            "services": {
              "systemd": {
                "crond"     : { "enabled" : "true", "ensureRunning" : "true" }
              }
            },
            "files": {
              "/etc/cfn/cfn-credentials" : {
                "content" : { "Fn::Join" : ["", [
                  "AWSAccessKeyId=", { "Ref" : "CfnLBAccessKey" }, "\n",
                  "AWSSecretKey=", {"Fn::GetAtt": ["CfnLBAccessKey",
                                    "SecretAccessKey"]}, "\n"
                ]]},
                "mode"    : "000400",
                "owner"   : "root",
                "group"   : "root"
              },
              "/etc/cfn/cfn-hup.conf" : {
                "content" : { "Fn::Join" : ["", [
                  "[main]\n",
                  "stack=", { "Ref" : "AWS::StackId" }, "\n",
                  "credential-file=/etc/cfn/cfn-credentials\n",
                  "region=", { "Ref" : "AWS::Region" }, "\n",
                  "interval=60\n"
                ]]},
                "mode"    : "000400",
                "owner"   : "root",
                "group"   : "root"
              },
              "/etc/cfn/hooks.conf" : {
                "content": { "Fn::Join" : ["", [
                  "[cfn-init]\n",
                  "triggers=post.update\n",
                  "path=Resources.LB_instance.Metadata\n",
                  "action=/opt/aws/bin/cfn-init -s ",
                  { "Ref": "AWS::StackId" },
                  "    -r LB_instance ",
                  "    --region ", { "Ref": "AWS::Region" }, "\n",
                  "runas=root\n",
                  "\n",
                  "[reload]\n",
                  "triggers=post.update\n",
                  "path=Resources.LB_instance.Metadata\n",
                  "action=systemctl reload-or-restart haproxy.service\n",
                  "runas=root\n"
                ]]},
                "mode"    : "000400",
                "owner"   : "root",
                "group"   : "root"
              },
              "/etc/haproxy/haproxy.cfg": {
                "content": "",
                "mode": "000644",
                "owner": "root",
                "group": "root"
              },
              "/tmp/cfn-hup-crontab.txt" : {
                "content" : { "Fn::Join" : ["", [
                "MAIL=\"\"\n",
                "\n",
                "* * * * * /opt/aws/bin/cfn-hup -f\n",
                "* * * * * /opt/aws/bin/cfn-push-stats ",
                " --watch ", { "Ref" : "latency_watcher" }, " --haproxy\n"
                ]]},
                "mode"    : "000600",
                "owner"   : "root",
                "group"   : "root"
              }
            }
          }
        }
      },
      "Properties": {
        "ImageId": "F17-x86_64-cfntools",
        "InstanceType": "m1.small",
        "KeyName": { "Ref": "KeyName" },
        "UserData": { "Fn::Base64": { "Fn::Join": ["", [
          "#!/bin/bash -v\n",
          "# Helper function\n",
          "function error_exit\n",
          "{\n",
          "  /opt/aws/bin/cfn-signal -e 1 -r \"$1\" '",
          { "Ref" : "WaitHandle" }, "'\n",
          "  exit 1\n",
          "}\n",

          "/opt/aws/bin/cfn-init -s ",
          { "Ref": "AWS::StackId" },
          "    -r LB_instance ",
          "    --region ", { "Ref": "AWS::Region" }, "\n",
          "# install cfn-hup crontab\n",
          "crontab /tmp/cfn-hup-crontab.txt\n",

          "# LB setup completed, signal success\n",
          "/opt/aws/bin/cfn-signal -e 0 -r \"LB server setup complete\" '",
          { "Ref" : "WaitHandle" }, "'\n"

        ]]}}
      }
    },
    "WaitHandle" : {
      "Type" : "AWS::CloudFormation::WaitConditionHandle"
    },

    "WaitCondition" : {
      "Type" : "AWS::CloudFormation::WaitCondition",
      "DependsOn" : "LB_instance",
      "Properties" : {
        "Handle" : {"Ref" : "WaitHandle"},
        "Timeout" : "600"
      }
    }
  },

  "Outputs": {
    "PublicIp": {
      "Value": { "Fn::GetAtt": [ "LB_instance", "PublicIp" ] },
      "Description": "instance IP"
    }
  }
}
'''


# Allow user to provide alternative nested stack template to the above
loadbalancer_opts = [
    cfg.StrOpt('loadbalancer_template',
               default=None,
               help='Custom template for the built-in '
                    'loadbalancer nested stack')]
cfg.CONF.register_opts(loadbalancer_opts)


class LoadBalancer(stack_resource.StackResource):

    listeners_schema = {
        'InstancePort': {
            'Type': 'Number',
            'Required': True,
            'Description': _('TCP port on which the instance server is'
                             ' listening.')},
        'LoadBalancerPort': {
            'Type': 'Number',
            'Required': True,
            'Description': _('The external load balancer port number.')},
        'Protocol': {
            'Type': 'String',
            'Required': True,
            'AllowedValues': ['TCP', 'HTTP'],
            'Description': _('The load balancer transport protocol to use.')},
        'SSLCertificateId': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'PolicyNames': {
            'Type': 'List',
            'Implemented': False,
            'Description': _('Not Implemented.')}
    }
    healthcheck_schema = {
        'HealthyThreshold': {
            'Type': 'Number',
            'Required': True,
            'Description': _('The number of consecutive health probe successes'
                             ' required before moving the instance to the'
                             ' healthy state.')},
        'Interval': {
            'Type': 'Number',
            'Required': True,
            'Description': _('The approximate interval, in seconds, between'
                             ' health checks of an individual instance.')},
        'Target': {
            'Type': 'String',
            'Required': True,
            'Description': _('The port being checked.')},
        'Timeout': {
            'Type': 'Number',
            'Required': True,
            'Description': _('Health probe timeout, in seconds.')},
        'UnhealthyThreshold': {
            'Type': 'Number',
            'Required': True,
            'Description': _('The number of consecutive health probe failures'
                             ' required before moving the instance to the'
                             ' unhealthy state')},
    }

    properties_schema = {
        'AvailabilityZones': {
            'Type': 'List',
            'Required': True,
            'Description': _('The Availability Zones in which to create the'
                             ' load balancer.')},
        'HealthCheck': {
            'Type': 'Map',
            'Schema': healthcheck_schema,
            'Description': _('An application health check for the'
                             ' instances.')},
        'Instances': {
            'Type': 'List',
            'Description': _('The list of instance IDs load balanced.')},
        'Listeners': {
            'Type': 'List', 'Required': True,
            'Schema': {'Type': 'Map', 'Schema': listeners_schema},
            'Description': _('One or more listeners for this load balancer.')},
        'AppCookieStickinessPolicy': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'LBCookieStickinessPolicy': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'SecurityGroups': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'Subnets': {
            'Type': 'List',
            'Implemented': False,
            'Description': _('Not Implemented.')}
    }
    attributes_schema = {
        "CanonicalHostedZoneName": ("The name of the hosted zone that is "
                                    "associated with the LoadBalancer."),
        "CanonicalHostedZoneNameID": ("The ID of the hosted zone name that is "
                                      "associated with the LoadBalancer."),
        "DNSName": "The DNS name for the LoadBalancer.",
        "SourceSecurityGroup.GroupName": ("The security group that you can use"
                                          " as part of your inbound rules for "
                                          "your LoadBalancer's back-end "
                                          "instances."),
        "SourceSecurityGroup.OwnerAlias": "Owner of the source security group."
    }
    update_allowed_keys = ('Properties',)
    update_allowed_properties = ('Instances',)

    def _haproxy_config(self, templ, instances):
        # initial simplifications:
        # - only one Listener
        # - only http (no tcp or ssl)
        #
        # option httpchk HEAD /check.txt HTTP/1.0
        gl = '''
    global
        daemon
        maxconn 256
        stats socket /tmp/.haproxy-stats

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

        health_chk = self.properties['HealthCheck']
        if health_chk:
            check = 'check inter %ss fall %s rise %s' % (
                    health_chk['Interval'],
                    health_chk['UnhealthyThreshold'],
                    health_chk['HealthyThreshold'])
            timeout_check = 'timeout check %ds' % int(health_chk['Timeout'])
        else:
            check = ''
            timeout_check = ''

        backend = '''
        default_backend servers

        backend servers
            balance roundrobin
            option http-server-close
            option forwardfor
            option httpchk
            %s
''' % timeout_check

        servers = []
        n = 1
        client = self.nova()
        for i in instances:
            ip = nova_utils.server_to_ipaddress(client, i) or '0.0.0.0'
            logger.debug('haproxy server:%s' % ip)
            servers.append('%sserver server%d %s:%s %s' % (spaces, n,
                                                           ip, inst_port,
                                                           check))
            n = n + 1

        return '%s%s%s%s\n' % (gl, frontend, backend, '\n'.join(servers))

    def get_parsed_template(self):
        if cfg.CONF.loadbalancer_template:
            with open(cfg.CONF.loadbalancer_template) as templ_fd:
                logger.info(_('Using custom loadbalancer template %s')
                            % cfg.CONF.loadbalancer_template)
                contents = templ_fd.read()
        else:
            contents = lb_template_default
        return template_format.parse(contents)

    def handle_create(self):
        templ = self.get_parsed_template()

        if self.properties['Instances']:
            md = templ['Resources']['LB_instance']['Metadata']
            files = md['AWS::CloudFormation::Init']['config']['files']
            cfg = self._haproxy_config(templ, self.properties['Instances'])
            files['/etc/haproxy/haproxy.cfg']['content'] = cfg

        # If the owning stack defines KeyName, we use that key for the nested
        # template, otherwise use no key
        try:
            param = {'KeyName': self.stack.parameters['KeyName']}
        except KeyError:
            del templ['Resources']['LB_instance']['Properties']['KeyName']
            del templ['Parameters']['KeyName']
            param = {}

        return self.create_with_template(templ, param)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        '''
        re-generate the Metadata
        save it to the db.
        rely on the cfn-hup to reconfigure HAProxy
        '''
        if 'Instances' in prop_diff:
            templ = self.get_parsed_template()
            cfg = self._haproxy_config(templ, prop_diff['Instances'])

            md = self.nested()['LB_instance'].metadata
            files = md['AWS::CloudFormation::Init']['config']['files']
            files['/etc/haproxy/haproxy.cfg']['content'] = cfg

            self.nested()['LB_instance'].metadata = md

    def handle_delete(self):
        return self.delete_nested()

    def validate(self):
        '''
        Validate any of the provided params
        '''
        res = super(LoadBalancer, self).validate()
        if res:
            return res

        if cfg.CONF.loadbalancer_template and \
                not os.access(cfg.CONF.loadbalancer_template, os.R_OK):
            msg = _('Custom LoadBalancer template can not be found')
            raise exception.StackValidationFailed(message=msg)

        health_chk = self.properties['HealthCheck']
        if health_chk:
            if float(health_chk['Interval']) < float(health_chk['Timeout']):
                return {'Error':
                        'Interval must be larger than Timeout'}

    def FnGetRefId(self):
        return unicode(self.name)

    def _resolve_attribute(self, name):
        '''
        We don't really support any of these yet.
        '''
        if name == 'DNSName':
            return self.get_output('PublicIp')
        elif name in self.attributes_schema:
            # Not sure if we should return anything for the other attribs
            # since they aren't really supported in any meaningful way
            return ''


def resource_mapping():
    return {
        'AWS::ElasticLoadBalancing::LoadBalancer': LoadBalancer,
    }
