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

from oslo_config import cfg
from oslo_log import log as logging
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common import template_format
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources import stack_resource

LOG = logging.getLogger(__name__)

lb_template_default = r'''
{
  "AWSTemplateFormatVersion": "2010-09-09",
  "Description": "Built in HAProxy server using Fedora 21 x64 cloud image",
  "Parameters" : {
    "KeyName" : {
      "Type" : "String"
    },
    "LbImageId" : {
      "Type" : "String",
      "Default" : "Fedora-Cloud-Base-20141203-21.x86_64"
    },
    "LbFlavor" : {
      "Type" : "String",
      "Default" : "m1.small"
    },
    "LBTimeout" : {
      "Type" : "String",
      "Default" : "600"
    },
    "SecurityGroups" : {
      "Type" : "CommaDelimitedList",
      "Default" : []
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
                "haproxy"        : [],
                "socat"          : []
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
              "/root/haproxy_tmp.te": {
                "mode": "000600",
                "owner": "root",
                "group": "root",
                "content": { "Fn::Join" : [ "", [
                  "module haproxy_tmp 1.0;\n",
                  "require { type tmp_t; type haproxy_t;",
                  "class sock_file { rename write create unlink link };",
                  "class dir { write remove_name add_name };}\n",
                  "allow haproxy_t ",
                  "tmp_t:dir { write remove_name add_name };\n",
                  "allow haproxy_t ",
                  "tmp_t:sock_file { rename write create unlink link};\n"
                 ]]}
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
        "ImageId": { "Ref": "LbImageId" },
        "InstanceType": { "Ref": "LbFlavor" },
        "KeyName": { "Ref": "KeyName" },
        "SecurityGroups": { "Ref": "SecurityGroups" },
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
          "    --region ", { "Ref": "AWS::Region" },
          " || error_exit 'Failed to run cfn-init'\n",

          "# HAProxy+SELinux, https://www.mankier.com/8/haproxy_selinux \n",

          "# this is exported by selinux-policy >=3.12.1.196\n",
          "setsebool haproxy_connect_any 1\n",

          "# when the location of haproxy stats file is fixed\n",
          "# in heat-cfntools and AWS::ElasticLoadBalancing::LoadBalancer\n",
          "# to point to /var/lib/haproxy/stats, \n",
          "# this next block can be removed.\n",
          "# compile custom module to allow /tmp files and sockets access\n",
          "cd /root\n",
          "checkmodule -M -m -o haproxy_tmp.mod haproxy_tmp.te\n",
          "semodule_package -o haproxy_tmp.pp -m haproxy_tmp.mod\n",
          "semodule -i haproxy_tmp.pp\n",
          "touch /tmp/.haproxy-stats\n",
          "semanage fcontext -a -t haproxy_tmpfs_t /tmp/.haproxy-stats\n",
          "restorecon -R -v /tmp/.haproxy-stats\n",

          "# install cfn-hup crontab\n",
          "crontab /tmp/cfn-hup-crontab.txt\n",

          "# restart haproxy service to catch initial changes\n",
          "systemctl reload-or-restart haproxy.service\n",

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
        "Timeout" : {"Ref" : "LBTimeout"}
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
               help=_('Custom template for the built-in '
                      'loadbalancer nested stack.'))]
cfg.CONF.register_opts(loadbalancer_opts)


class LoadBalancer(stack_resource.StackResource):
    """Implements a HAProxy-bearing instance as a nested stack.

    The template for the nested stack can be redefined with
    ``loadbalancer_template`` option in ``heat.conf``.

    Generally the image used for the instance must have the following
    packages installed or available for installation at runtime::

        - heat-cfntools and its dependencies like python-psutil
        - cronie
        - socat
        - haproxy

    Current default builtin template uses Fedora 21 x86_64 base cloud image
    (https://getfedora.org/cloud/download/)
    and apart from installing packages goes through some hoops
    around SELinux due to pecularities of heat-cfntools.
    """

    PROPERTIES = (
        AVAILABILITY_ZONES, HEALTH_CHECK, INSTANCES, LISTENERS,
        APP_COOKIE_STICKINESS_POLICY, LBCOOKIE_STICKINESS_POLICY,
        SECURITY_GROUPS, SUBNETS,
    ) = (
        'AvailabilityZones', 'HealthCheck', 'Instances', 'Listeners',
        'AppCookieStickinessPolicy', 'LBCookieStickinessPolicy',
        'SecurityGroups', 'Subnets',
    )

    _HEALTH_CHECK_KEYS = (
        HEALTH_CHECK_HEALTHY_THRESHOLD, HEALTH_CHECK_INTERVAL,
        HEALTH_CHECK_TARGET, HEALTH_CHECK_TIMEOUT,
        HEALTH_CHECK_UNHEALTHY_THRESHOLD,
    ) = (
        'HealthyThreshold', 'Interval',
        'Target', 'Timeout',
        'UnhealthyThreshold',
    )

    _LISTENER_KEYS = (
        LISTENER_INSTANCE_PORT, LISTENER_LOAD_BALANCER_PORT, LISTENER_PROTOCOL,
        LISTENER_SSLCERTIFICATE_ID, LISTENER_POLICY_NAMES,
    ) = (
        'InstancePort', 'LoadBalancerPort', 'Protocol',
        'SSLCertificateId', 'PolicyNames',
    )

    ATTRIBUTES = (
        CANONICAL_HOSTED_ZONE_NAME, CANONICAL_HOSTED_ZONE_NAME_ID, DNS_NAME,
        SOURCE_SECURITY_GROUP_GROUP_NAME, SOURCE_SECURITY_GROUP_OWNER_ALIAS,
    ) = (
        'CanonicalHostedZoneName', 'CanonicalHostedZoneNameID', 'DNSName',
        'SourceSecurityGroup.GroupName', 'SourceSecurityGroup.OwnerAlias',
    )

    properties_schema = {
        AVAILABILITY_ZONES: properties.Schema(
            properties.Schema.LIST,
            _('The Availability Zones in which to create the load balancer.'),
            required=True
        ),
        HEALTH_CHECK: properties.Schema(
            properties.Schema.MAP,
            _('An application health check for the instances.'),
            schema={
                HEALTH_CHECK_HEALTHY_THRESHOLD: properties.Schema(
                    properties.Schema.INTEGER,
                    _('The number of consecutive health probe successes '
                      'required before moving the instance to the '
                      'healthy state.'),
                    required=True
                ),
                HEALTH_CHECK_INTERVAL: properties.Schema(
                    properties.Schema.INTEGER,
                    _('The approximate interval, in seconds, between '
                      'health checks of an individual instance.'),
                    required=True
                ),
                HEALTH_CHECK_TARGET: properties.Schema(
                    properties.Schema.STRING,
                    _('The port being checked.'),
                    required=True
                ),
                HEALTH_CHECK_TIMEOUT: properties.Schema(
                    properties.Schema.INTEGER,
                    _('Health probe timeout, in seconds.'),
                    required=True
                ),
                HEALTH_CHECK_UNHEALTHY_THRESHOLD: properties.Schema(
                    properties.Schema.INTEGER,
                    _('The number of consecutive health probe failures '
                      'required before moving the instance to the '
                      'unhealthy state'),
                    required=True
                ),
            }
        ),
        INSTANCES: properties.Schema(
            properties.Schema.LIST,
            _('The list of instance IDs load balanced.'),
            update_allowed=True
        ),
        LISTENERS: properties.Schema(
            properties.Schema.LIST,
            _('One or more listeners for this load balancer.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    LISTENER_INSTANCE_PORT: properties.Schema(
                        properties.Schema.INTEGER,
                        _('TCP port on which the instance server is '
                          'listening.'),
                        required=True
                    ),
                    LISTENER_LOAD_BALANCER_PORT: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The external load balancer port number.'),
                        required=True
                    ),
                    LISTENER_PROTOCOL: properties.Schema(
                        properties.Schema.STRING,
                        _('The load balancer transport protocol to use.'),
                        required=True,
                        constraints=[
                            constraints.AllowedValues(['TCP', 'HTTP']),
                        ]
                    ),
                    LISTENER_SSLCERTIFICATE_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('Not Implemented.'),
                        implemented=False
                    ),
                    LISTENER_POLICY_NAMES: properties.Schema(
                        properties.Schema.LIST,
                        _('Not Implemented.'),
                        implemented=False
                    ),
                },
            ),
            required=True
        ),
        APP_COOKIE_STICKINESS_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        LBCOOKIE_STICKINESS_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('List of Security Groups assigned on current LB.'),
            update_allowed=True
        ),
        SUBNETS: properties.Schema(
            properties.Schema.LIST,
            _('Not Implemented.'),
            implemented=False
        ),
    }

    attributes_schema = {
        CANONICAL_HOSTED_ZONE_NAME: attributes.Schema(
            _("The name of the hosted zone that is associated with the "
              "LoadBalancer."),
            type=attributes.Schema.STRING
        ),
        CANONICAL_HOSTED_ZONE_NAME_ID: attributes.Schema(
            _("The ID of the hosted zone name that is associated with the "
              "LoadBalancer."),
            type=attributes.Schema.STRING
        ),
        DNS_NAME: attributes.Schema(
            _("The DNS name for the LoadBalancer."),
            type=attributes.Schema.STRING
        ),
        SOURCE_SECURITY_GROUP_GROUP_NAME: attributes.Schema(
            _("The security group that you can use as part of your inbound "
              "rules for your LoadBalancer's back-end instances."),
            type=attributes.Schema.STRING
        ),
        SOURCE_SECURITY_GROUP_OWNER_ALIAS: attributes.Schema(
            _("Owner of the source security group."),
            type=attributes.Schema.STRING
        ),
    }

    def _haproxy_config_global(self):
        return '''
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

    def _haproxy_config_frontend(self):
        listener = self.properties[self.LISTENERS][0]
        lb_port = listener[self.LISTENER_LOAD_BALANCER_PORT]
        return '''
frontend http
    bind *:%s
    default_backend servers
''' % (lb_port)

    def _haproxy_config_backend(self):
        health_chk = self.properties[self.HEALTH_CHECK]
        if health_chk:
            timeout = int(health_chk[self.HEALTH_CHECK_TIMEOUT])
            timeout_check = 'timeout check %ds' % timeout
            spaces = '    '
        else:
            timeout_check = ''
            spaces = ''

        return '''
backend servers
    balance roundrobin
    option http-server-close
    option forwardfor
    option httpchk
%s%s
''' % (spaces, timeout_check)

    def _haproxy_config_servers(self, instances):
        listener = self.properties[self.LISTENERS][0]
        inst_port = listener[self.LISTENER_INSTANCE_PORT]
        spaces = '    '
        check = ''
        health_chk = self.properties[self.HEALTH_CHECK]
        if health_chk:
            check = ' check inter %ss fall %s rise %s' % (
                    health_chk[self.HEALTH_CHECK_INTERVAL],
                    health_chk[self.HEALTH_CHECK_UNHEALTHY_THRESHOLD],
                    health_chk[self.HEALTH_CHECK_HEALTHY_THRESHOLD])

        servers = []
        n = 1
        nova_cp = self.client_plugin('nova')
        for i in instances or []:
            ip = nova_cp.server_to_ipaddress(i) or '0.0.0.0'
            LOG.debug('haproxy server:%s', ip)
            servers.append('%sserver server%d %s:%s%s' % (spaces, n,
                                                          ip, inst_port,
                                                          check))
            n = n + 1
        return '\n'.join(servers)

    def _haproxy_config(self, instances):
        # initial simplifications:
        # - only one Listener
        # - only http (no tcp or ssl)
        #
        # option httpchk HEAD /check.txt HTTP/1.0
        return '%s%s%s%s\n' % (self._haproxy_config_global(),
                               self._haproxy_config_frontend(),
                               self._haproxy_config_backend(),
                               self._haproxy_config_servers(instances))

    def get_parsed_template(self):
        if cfg.CONF.loadbalancer_template:
            with open(cfg.CONF.loadbalancer_template) as templ_fd:
                LOG.info('Using custom loadbalancer template %s',
                         cfg.CONF.loadbalancer_template)
                contents = templ_fd.read()
        else:
            contents = lb_template_default
        return template_format.parse(contents)

    def child_params(self):
        params = {}

        params['SecurityGroups'] = self.properties[self.SECURITY_GROUPS]
        # If the owning stack defines KeyName, we use that key for the nested
        # template, otherwise use no key
        for magic_param in ('KeyName', 'LbFlavor', 'LBTimeout', 'LbImageId'):
            if magic_param in self.stack.parameters:
                params[magic_param] = self.stack.parameters[magic_param]

        return params

    def child_template(self):
        templ = self.get_parsed_template()

        # If the owning stack defines KeyName, we use that key for the nested
        # template, otherwise use no key
        if 'KeyName' not in self.stack.parameters:
            del templ['Resources']['LB_instance']['Properties']['KeyName']
            del templ['Parameters']['KeyName']

        return templ

    def handle_create(self):
        templ = self.child_template()
        params = self.child_params()

        if self.properties[self.INSTANCES]:
            md = templ['Resources']['LB_instance']['Metadata']
            files = md['AWS::CloudFormation::Init']['config']['files']
            cfg = self._haproxy_config(self.properties[self.INSTANCES])
            files['/etc/haproxy/haproxy.cfg']['content'] = cfg

        return self.create_with_template(templ, params)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Re-generate the Metadata.

        Save it to the db.
        Rely on the cfn-hup to reconfigure HAProxy.
        """

        new_props = json_snippet.properties(self.properties_schema,
                                            self.context)

        # Valid use cases are:
        # - Membership controlled by members property in template
        # - Empty members property in template; membership controlled by
        #   "updates" triggered from autoscaling group.
        # Mixing the two will lead to undefined behaviour.
        if (self.INSTANCES in prop_diff and
                (self.properties[self.INSTANCES] is not None or
                 new_props[self.INSTANCES] is not None)):
            cfg = self._haproxy_config(prop_diff[self.INSTANCES])

            md = self.nested()['LB_instance'].metadata_get()
            files = md['AWS::CloudFormation::Init']['config']['files']
            files['/etc/haproxy/haproxy.cfg']['content'] = cfg

            self.nested()['LB_instance'].metadata_set(md)

        if self.SECURITY_GROUPS in prop_diff:
            templ = self.child_template()
            params = self.child_params()
            params['SecurityGroups'] = new_props[self.SECURITY_GROUPS]
            self.update_with_template(templ, params)

    def check_update_complete(self, updater):
        """Because we are not calling update_with_template, return True."""
        return True

    def validate(self):
        """Validate any of the provided params."""
        res = super(LoadBalancer, self).validate()
        if res:
            return res

        if (cfg.CONF.loadbalancer_template and
                not os.access(cfg.CONF.loadbalancer_template, os.R_OK)):
            msg = _('Custom LoadBalancer template can not be found')
            raise exception.StackValidationFailed(message=msg)

        health_chk = self.properties[self.HEALTH_CHECK]
        if health_chk:
            interval = float(health_chk[self.HEALTH_CHECK_INTERVAL])
            timeout = float(health_chk[self.HEALTH_CHECK_TIMEOUT])
            if interval < timeout:
                return {'Error':
                        'Interval must be larger than Timeout'}

    def get_reference_id(self):
        return six.text_type(self.name)

    def _resolve_attribute(self, name):
        """We don't really support any of these yet."""
        if name == self.DNS_NAME:
            try:
                return self.get_output('PublicIp')
            except exception.NotFound:
                raise exception.InvalidTemplateAttribute(resource=self.name,
                                                         key=name)
        elif name in self.attributes_schema:
            # Not sure if we should return anything for the other attribs
            # since they aren't really supported in any meaningful way
            return ''


def resource_mapping():
    return {
        'AWS::ElasticLoadBalancing::LoadBalancer': LoadBalancer,
    }
