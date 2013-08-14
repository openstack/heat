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

from heat.engine import clients
from heat.engine import resource

from heat.common import exception
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class SecurityGroup(resource.Resource):
    properties_schema = {'GroupDescription': {'Type': 'String',
                                              'Required': True},
                         'VpcId': {'Type': 'String'},
                         'SecurityGroupIngress': {'Type': 'List'},
                         'SecurityGroupEgress': {'Type': 'List'}}

    def handle_create(self):
        if self.properties['VpcId'] and clients.neutronclient is not None:
            self._handle_create_neutron()
        else:
            self._handle_create_nova()

    def _convert_to_neutron_rule(self, direction, sg_rule):
        return {
            'direction': direction,
            'ethertype': 'IPv4',
            'remote_ip_prefix': sg_rule.get('CidrIp'),
            'port_range_min': sg_rule.get('FromPort'),
            'port_range_max': sg_rule.get('ToPort'),
            'protocol': sg_rule.get('IpProtocol'),
            # Neutron understands both names and ids
            'remote_group_id': sg_rule.get('SourceSecurityGroupId') or
            sg_rule.get('SourceSecurityGroupName'),
            'security_group_id': self.resource_id
        }

    def _handle_create_neutron(self):
        from neutronclient.common.exceptions import NeutronClientException
        client = self.neutron()

        sec = client.create_security_group({'security_group': {
            'name': self.physical_resource_name(),
            'description': self.properties['GroupDescription']}
        })['security_group']

        def sanitize_security_group(i):
            # Neutron only accepts positive ints
            if i.get('FromPort') is not None and int(i['FromPort']) < 0:
                i['FromPort'] = None
            if i.get('ToPort') is not None and int(i['ToPort']) < 0:
                i['ToPort'] = None
            if i.get('FromPort') is None and i.get('ToPort') is None:
                i['CidrIp'] = None

        self.resource_id_set(sec['id'])
        if self.properties['SecurityGroupIngress']:
            for i in self.properties['SecurityGroupIngress']:
                sanitize_security_group(i)
                try:
                    rule = client.create_security_group_rule({
                        'security_group_rule':
                        self._convert_to_neutron_rule('ingress', i)
                    })
                except NeutronClientException as ex:
                    if ex.status_code == 409:
                        # no worries, the rule is already there
                        pass
                    else:
                        # unexpected error
                        raise
        if self.properties['SecurityGroupEgress']:
            # Delete the default rules which allow all egress traffic
            for rule in sec['security_group_rules']:
                if rule['direction'] == 'egress':
                    client.delete_security_group_rule(rule['id'])

            for i in self.properties['SecurityGroupEgress']:
                sanitize_security_group(i)
                try:
                    rule = client.create_security_group_rule({
                        'security_group_rule':
                        self._convert_to_neutron_rule('egress', i)
                    })
                except NeutronClientException as ex:
                    if ex.status_code == 409:
                        # no worries, the rule is already there
                        pass
                    else:
                        # unexpected error
                        raise

    def _handle_create_nova(self):
        sec = None

        groups = self.nova().security_groups.list()
        for group in groups:
            if group.name == self.physical_resource_name():
                sec = group
                break

        if not sec:
            sec = self.nova().security_groups.create(
                self.physical_resource_name(),
                self.properties['GroupDescription'])

        self.resource_id_set(sec.id)
        if self.properties['SecurityGroupIngress']:
            rules_client = self.nova().security_group_rules
            for i in self.properties['SecurityGroupIngress']:
                source_group_id = None
                if i.get('SourceSecurityGroupId') is not None:
                    source_group_id = i['SourceSecurityGroupId']
                elif i.get('SourceSecurityGroupName') is not None:
                    for group in groups:
                        if group.name == i['SourceSecurityGroupName']:
                            source_group_id = group.id
                            break
                try:
                    rule = rules_client.create(
                        sec.id,
                        i.get('IpProtocol'),
                        i.get('FromPort'),
                        i.get('ToPort'),
                        i.get('CidrIp'),
                        source_group_id)
                except clients.novaclient.exceptions.BadRequest as ex:
                    if ex.message.find('already exists') >= 0:
                        # no worries, the rule is already there
                        pass
                    else:
                        # unexpected error
                        raise

    def handle_delete(self):
        if self.properties['VpcId'] and clients.neutronclient is not None:
            self._handle_delete_neutron()
        else:
            self._handle_delete_nova()

    def _handle_delete_nova(self):
        if self.resource_id is not None:
            try:
                sec = self.nova().security_groups.get(self.resource_id)
            except clients.novaclient.exceptions.NotFound:
                pass
            else:
                for rule in sec.rules:
                    try:
                        self.nova().security_group_rules.delete(rule['id'])
                    except clients.novaclient.exceptions.NotFound:
                        pass

                self.nova().security_groups.delete(self.resource_id)
            self.resource_id = None

    def _handle_delete_neutron(self):
        from neutronclient.common.exceptions import NeutronClientException
        client = self.neutron()

        if self.resource_id is not None:
            try:
                sec = client.show_security_group(
                    self.resource_id)['security_group']
            except NeutronClientException as ex:
                if ex.status_code != 404:
                    raise
            else:
                for rule in sec['security_group_rules']:
                    try:
                        client.delete_security_group_rule(rule['id'])
                    except NeutronClientException as ex:
                        if ex.status_code != 404:
                            raise

                try:
                    client.delete_security_group(self.resource_id)
                except NeutronClientException as ex:
                    if ex.status_code != 404:
                        raise
            self.resource_id = None

    def FnGetRefId(self):
        if self.properties['VpcId']:
            return super(SecurityGroup, self).FnGetRefId()
        else:
            return self.physical_resource_name()

    def validate(self):
        res = super(SecurityGroup, self).validate()
        if res:
            return res

        if self.properties['SecurityGroupEgress'] and not(
                self.properties['VpcId'] and
                clients.neutronclient is not None):
            raise exception.EgressRuleNotAllowed()


def resource_mapping():
    return {
        'AWS::EC2::SecurityGroup': SecurityGroup,
    }
