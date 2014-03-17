
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

from heat.common import exception
from heat.engine import clients
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


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
            _('Physical ID of the VPC.')
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
        if self.properties[self.VPC_ID] and clients.neutronclient is not None:
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
        from neutronclient.common.exceptions import NeutronClientException
        client = self.neutron()

        sec = client.create_security_group({'security_group': {
            'name': self.physical_resource_name(),
            'description': self.properties[self.GROUP_DESCRIPTION]}
        })['security_group']

        def sanitize_security_group(i):
            # Neutron only accepts positive ints
            if (i.get(self.RULE_FROM_PORT) is not None and
                    int(i[self.RULE_FROM_PORT]) < 0):
                i[self.RULE_FROM_PORT] = None
            if (i.get(self.RULE_TO_PORT) is not None and
                    int(i[self.RULE_TO_PORT]) < 0):
                i[self.RULE_TO_PORT] = None
            if (i.get(self.RULE_FROM_PORT) is None and
                    i.get(self.RULE_TO_PORT) is None):
                i[self.RULE_CIDR_IP] = None

        self.resource_id_set(sec['id'])
        if self.properties[self.SECURITY_GROUP_INGRESS]:
            for i in self.properties[self.SECURITY_GROUP_INGRESS]:
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
        if self.properties[self.SECURITY_GROUP_EGRESS]:
            # Delete the default rules which allow all egress traffic
            for rule in sec['security_group_rules']:
                if rule['direction'] == 'egress':
                    client.delete_security_group_rule(rule['id'])

            for i in self.properties[self.SECURITY_GROUP_EGRESS]:
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
                self.properties[self.GROUP_DESCRIPTION])

        self.resource_id_set(sec.id)
        if self.properties[self.SECURITY_GROUP_INGRESS]:
            rules_client = self.nova().security_group_rules
            for i in self.properties[self.SECURITY_GROUP_INGRESS]:
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
                    rules_client.create(
                        sec.id,
                        i.get(self.RULE_IP_PROTOCOL),
                        i.get(self.RULE_FROM_PORT),
                        i.get(self.RULE_TO_PORT),
                        i.get(self.RULE_CIDR_IP),
                        source_group_id)
                except clients.novaclient.exceptions.BadRequest as ex:
                    if ex.message.find('already exists') >= 0:
                        # no worries, the rule is already there
                        pass
                    else:
                        # unexpected error
                        raise

    def handle_delete(self):
        if self.properties[self.VPC_ID] and clients.neutronclient is not None:
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
            self.resource_id_set(None)

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
            self.resource_id_set(None)

    def FnGetRefId(self):
        if self.properties[self.VPC_ID]:
            return super(SecurityGroup, self).FnGetRefId()
        else:
            return self.physical_resource_name()

    def validate(self):
        res = super(SecurityGroup, self).validate()
        if res:
            return res

        if self.properties[self.SECURITY_GROUP_EGRESS] and not(
                self.properties[self.VPC_ID] and
                clients.neutronclient is not None):
            raise exception.EgressRuleNotAllowed()


class SecurityGroupNotFound(exception.HeatException):
    msg_fmt = _('Security Group "%(group_name)s" not found')


def resource_mapping():
    return {
        'AWS::EC2::SecurityGroup': SecurityGroup,
    }
