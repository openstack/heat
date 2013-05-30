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

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class SecurityGroup(resource.Resource):
    properties_schema = {'GroupDescription': {'Type': 'String',
                                              'Required': True},
                         'VpcId': {'Type': 'String'},
                         'SecurityGroupIngress': {'Type': 'List'},
                         'SecurityGroupEgress': {'Type': 'List'}}

    def handle_create(self):
        if self.properties['VpcId'] and clients.quantumclient is not None:
            self._handle_create_quantum()
        else:
            self._handle_create_nova()

    def _handle_create_quantum(self):
        from quantumclient.common.exceptions import QuantumClientException
        client = self.quantum()

        sec = client.create_security_group({'security_group': {
            'name': self.physical_resource_name(),
            'description': self.properties['GroupDescription']}
        })['security_group']

        self.resource_id_set(sec['id'])
        if self.properties['SecurityGroupIngress']:
            for i in self.properties['SecurityGroupIngress']:
                # Quantum only accepts positive ints
                if int(i['FromPort']) < 0:
                    i['FromPort'] = None
                if int(i['ToPort']) < 0:
                    i['ToPort'] = None
                if i['FromPort'] is None and i['ToPort'] is None:
                    i['CidrIp'] = None

                try:
                    rule = client.create_security_group_rule({
                        'security_group_rule': {
                            'direction': 'ingress',
                            'remote_ip_prefix': i['CidrIp'],
                            'port_range_min': i['FromPort'],
                            'ethertype': 'IPv4',
                            'port_range_max': i['ToPort'],
                            'protocol': i['IpProtocol'],
                            'security_group_id': sec['id']
                        }
                    })
                except QuantumClientException as ex:
                    if ex.status_code == 409:
                        # no worries, the rule is already there
                        pass
                    else:
                        # unexpected error
                        raise
        if self.properties['SecurityGroupEgress']:
            for i in self.properties['SecurityGroupEgress']:
                try:
                    rule = client.create_security_group_rule({
                        'security_group_rule': {
                            'direction': 'egress',
                            'remote_ip_prefix': i['CidrIp'],
                            'port_range_min': i['FromPort'],
                            'ethertype': 'IPv4',
                            'port_range_max': i['ToPort'],
                            'protocol': i['IpProtocol'],
                            'security_group_id': sec['id']
                        }
                    })
                except QuantumClientException as ex:
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
                try:
                    rule = rules_client.create(sec.id,
                                               i['IpProtocol'],
                                               i['FromPort'],
                                               i['ToPort'],
                                               i['CidrIp'])
                except clients.novaclient.exceptions.BadRequest as ex:
                    if ex.message.find('already exists') >= 0:
                        # no worries, the rule is already there
                        pass
                    else:
                        # unexpected error
                        raise

    def handle_delete(self):
        if self.properties['VpcId'] and clients.quantumclient is not None:
            self._handle_delete_quantum()
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

    def _handle_delete_quantum(self):
        from quantumclient.common.exceptions import QuantumClientException
        client = self.quantum()

        if self.resource_id is not None:
            try:
                sec = client.show_security_group(
                    self.resource_id)['security_group']
            except QuantumClientException as ex:
                if ex.status_code != 404:
                    raise
            else:
                for rule in sec['security_group_rules']:
                    try:
                        client.delete_security_group_rule(rule['id'])
                    except QuantumClientException as ex:
                        if ex.status_code != 404:
                            raise

                try:
                    client.delete_security_group(self.resource_id)
                except QuantumClientException as ex:
                    if ex.status_code != 404:
                        raise
            self.resource_id = None

    def FnGetRefId(self):
        if self.properties['VpcId']:
            return super(SecurityGroup, self).FnGetRefId()
        else:
            return self.physical_resource_name()


def resource_mapping():
    return {
        'AWS::EC2::SecurityGroup': SecurityGroup,
    }
