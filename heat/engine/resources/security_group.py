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

import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import properties
from heat.engine import resource


class SecurityGroup(resource.Resource):
    PROPERTIES = (
        GROUP_DESCRIPTION, VPC_ID, SECURITY_GROUP_INGRESS,
        SECURITY_GROUP_EGRESS,
    ) = (
        'GroupDescription', 'VpcId', 'SecurityGroupIngress',
        'SecurityGroupEgress',
    )

    _RULE_KEYS = (
        RULE_CIDR_IP, RULE_FROM_PORT, RULE_TO_PORT, RULE_IP_PROTOCOL,
        RULE_SOURCE_SECURITY_GROUP_ID, RULE_SOURCE_SECURITY_GROUP_NAME,
        RULE_SOURCE_SECURITY_GROUP_OWNER_ID,
    ) = (
        'CidrIp', 'FromPort', 'ToPort', 'IpProtocol',
        'SourceSecurityGroupId', 'SourceSecurityGroupName',
        'SourceSecurityGroupOwnerId',
    )

    _rule_schema = {
        RULE_CIDR_IP: properties.Schema(
            properties.Schema.STRING
        ),
        RULE_FROM_PORT: properties.Schema(
            properties.Schema.STRING
        ),
        RULE_TO_PORT: properties.Schema(
            properties.Schema.STRING
        ),
        RULE_IP_PROTOCOL: properties.Schema(
            properties.Schema.STRING
        ),
        RULE_SOURCE_SECURITY_GROUP_ID: properties.Schema(
            properties.Schema.STRING
        ),
        RULE_SOURCE_SECURITY_GROUP_NAME: properties.Schema(
            properties.Schema.STRING
        ),
        RULE_SOURCE_SECURITY_GROUP_OWNER_ID: properties.Schema(
            properties.Schema.STRING,
            implemented=False
        ),
    }

    properties_schema = {
        GROUP_DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the security group.'),
            required=True
        ),
        VPC_ID: properties.Schema(
            properties.Schema.STRING,
            _('Physical ID of the VPC. Not implemented.')
        ),
        SECURITY_GROUP_INGRESS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of security group ingress rules.'),
                schema=_rule_schema,
            )
        ),
        SECURITY_GROUP_EGRESS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of security group egress rules.'),
                schema=_rule_schema,
            )
        ),
    }

    def handle_create(self):
        if self.is_using_neutron():
            self._handle_create_neutron()
        else:
            self._handle_create_nova()

    def _convert_to_neutron_rule(self, direction, sg_rule):
        return {
            'direction': direction,
            'ethertype': 'IPv4',
            'remote_ip_prefix': sg_rule.get(self.RULE_CIDR_IP),
            'port_range_min': sg_rule.get(self.RULE_FROM_PORT),
            'port_range_max': sg_rule.get(self.RULE_TO_PORT),
            'protocol': sg_rule.get(self.RULE_IP_PROTOCOL),
            # Neutron understands both names and ids
            'remote_group_id': sg_rule.get(self.RULE_SOURCE_SECURITY_GROUP_ID)
            or sg_rule.get(self.RULE_SOURCE_SECURITY_GROUP_NAME),
            'security_group_id': self.resource_id
        }

    def _handle_create_neutron(self):
        client = self.neutron()

        sec = client.create_security_group({'security_group': {
            'name': self.physical_resource_name(),
            'description': self.properties[self.GROUP_DESCRIPTION]}
        })['security_group']

        self.resource_id_set(sec['id'])
        self._delete_default_egress_rules_neutron(client, sec)
        self._create_rules_neutron(client, sec, self.properties)

    def _delete_default_egress_rules_neutron(self, client, sec):
        """Delete the default rules which allow all egress traffic."""
        if self.properties[self.SECURITY_GROUP_EGRESS]:
            for rule in sec['security_group_rules']:
                if rule['direction'] == 'egress':
                    client.delete_security_group_rule(rule['id'])

    def _create_rules_neutron(self, client, sec, props):

        def create_rule(rule, direction):
            # Neutron only accepts positive ints
            if (rule.get(self.RULE_FROM_PORT) is not None and
                    int(rule[self.RULE_FROM_PORT]) < 0):
                rule[self.RULE_FROM_PORT] = None
            if (rule.get(self.RULE_TO_PORT) is not None and
                    int(rule[self.RULE_TO_PORT]) < 0):
                rule[self.RULE_TO_PORT] = None
            if (rule.get(self.RULE_FROM_PORT) is None and
                    rule.get(self.RULE_TO_PORT) is None):
                rule[self.RULE_CIDR_IP] = None

            try:
                client.create_security_group_rule({
                    'security_group_rule':
                    self._convert_to_neutron_rule(direction, rule)
                })
            except Exception as ex:
                # ignore error if the group already exists
                if not self.client_plugin('neutron').is_conflict(ex):
                    raise

        if props[self.SECURITY_GROUP_INGRESS]:
            for i in props[self.SECURITY_GROUP_INGRESS]:
                create_rule(i, 'ingress')

        if props[self.SECURITY_GROUP_EGRESS]:
            for i in props[self.SECURITY_GROUP_EGRESS]:
                create_rule(i, 'egress')

    def _handle_create_nova(self):
        sec = None
        client = self.nova()
        groups = client.security_groups.list()
        for group in groups:
            if group.name == self.physical_resource_name():
                sec = group
                break

        if not sec:
            sec = client.security_groups.create(
                self.physical_resource_name(),
                self.properties[self.GROUP_DESCRIPTION])

        self.resource_id_set(sec.id)
        if self.properties[self.SECURITY_GROUP_INGRESS]:
            self._create_rules_nova(client, groups, sec, self.properties)

    def _create_rules_nova(self, client, groups, sec, props):
        for i in props[self.SECURITY_GROUP_INGRESS]:
            source_group_id = None
            if i.get(self.RULE_SOURCE_SECURITY_GROUP_ID) is not None:
                source_group_id = i[self.RULE_SOURCE_SECURITY_GROUP_ID]
            elif i.get(self.RULE_SOURCE_SECURITY_GROUP_NAME) is not None:
                rule_name = i[self.RULE_SOURCE_SECURITY_GROUP_NAME]
                for group in groups:
                    if group.name == rule_name:
                        source_group_id = group.id
                        break
                else:
                    raise SecurityGroupNotFound(group_name=rule_name)
            try:
                client.security_group_rules.create(
                    sec.id,
                    i.get(self.RULE_IP_PROTOCOL),
                    i.get(self.RULE_FROM_PORT),
                    i.get(self.RULE_TO_PORT),
                    i.get(self.RULE_CIDR_IP),
                    source_group_id)
            except Exception as ex:
                # ignore error if the group already exists
                if not (self.client_plugin('nova').is_bad_request(ex) and
                        'already exists' in six.text_type(ex)):
                    raise

    def handle_delete(self):
        if self.is_using_neutron():
            self._handle_delete_neutron()
        else:
            self._handle_delete_nova()

    def _handle_delete_nova(self):
        client = self.nova()
        if self.resource_id is not None:
            try:
                sec = client.security_groups.get(self.resource_id)
            except Exception as e:
                self.client_plugin('nova').ignore_not_found(e)
            else:
                self._delete_rules_nova(client, sec)
                client.security_groups.delete(self.resource_id)

    def _delete_rules_nova(self, client, sec):
        for rule in sec.rules:
            try:
                client.security_group_rules.delete(rule['id'])
            except Exception as e:
                self.client_plugin('nova').ignore_not_found(e)

    def _handle_delete_neutron(self):
        client = self.neutron()

        if self.resource_id is not None:
            try:
                sec = client.show_security_group(
                    self.resource_id)['security_group']
            except Exception as ex:
                self.client_plugin('neutron').ignore_not_found(ex)
            else:
                self._delete_rules_neutron(client, sec)
                try:
                    client.delete_security_group(self.resource_id)
                except Exception as ex:
                    self.client_plugin('neutron').ignore_not_found(ex)

    def _delete_rules_neutron(self, client, sec):
        for rule in sec['security_group_rules']:
            try:
                client.delete_security_group_rule(rule['id'])
            except Exception as ex:
                self.client_plugin('neutron').ignore_not_found(ex)

    def FnGetRefId(self):
        if self.is_using_neutron():
            return super(SecurityGroup, self).FnGetRefId()
        else:
            return self.physical_resource_name()

    def validate(self):
        res = super(SecurityGroup, self).validate()
        if res:
            return res

        if (self.properties[self.SECURITY_GROUP_EGRESS] and
                not self.is_using_neutron()):
            raise exception.EgressRuleNotAllowed()


class SecurityGroupNotFound(exception.HeatException):
    msg_fmt = _('Security Group "%(group_name)s" not found')


def resource_mapping():
    return {
        'AWS::EC2::SecurityGroup': SecurityGroup,
    }
