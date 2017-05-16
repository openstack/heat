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


class NeutronSecurityGroup(object):

    def __init__(self, sg):
        self.sg = sg
        self.client = sg.client('neutron')
        self.plugin = sg.client_plugin('neutron')

    def _convert_to_neutron_rule(self, sg_rule):
        return {
            'direction': sg_rule['direction'],
            'ethertype': 'IPv4',
            'remote_ip_prefix': sg_rule.get(self.sg.RULE_CIDR_IP),
            'port_range_min': sg_rule.get(self.sg.RULE_FROM_PORT),
            'port_range_max': sg_rule.get(self.sg.RULE_TO_PORT),
            'protocol': sg_rule.get(self.sg.RULE_IP_PROTOCOL),
            'remote_group_id': sg_rule.get(
                self.sg.RULE_SOURCE_SECURITY_GROUP_ID),
            'security_group_id': self.sg.resource_id
        }

    def _res_rules_to_common(self, api_rules):
        rules = {}
        for nr in api_rules:
            rule = {}
            rule[self.sg.RULE_FROM_PORT] = nr['port_range_min']
            rule[self.sg.RULE_TO_PORT] = nr['port_range_max']
            rule[self.sg.RULE_IP_PROTOCOL] = nr['protocol']
            rule['direction'] = nr['direction']
            rule[self.sg.RULE_CIDR_IP] = nr['remote_ip_prefix']
            rule[self.sg.RULE_SOURCE_SECURITY_GROUP_ID
                 ] = nr['remote_group_id']
            rules[nr['id']] = rule
        return rules

    def _prop_rules_to_common(self, props, direction):
        rules = []
        prs = props.get(direction) or []
        for pr in prs:
            rule = dict(pr)
            rule.pop(self.sg.RULE_SOURCE_SECURITY_GROUP_OWNER_ID)
            # Neutron only accepts positive ints
            from_port = pr.get(self.sg.RULE_FROM_PORT)
            if from_port is not None:
                from_port = int(from_port)
                if from_port < 0:
                    from_port = None
            rule[self.sg.RULE_FROM_PORT] = from_port
            to_port = pr.get(self.sg.RULE_TO_PORT)
            if to_port is not None:
                to_port = int(to_port)
                if to_port < 0:
                    to_port = None
            rule[self.sg.RULE_TO_PORT] = to_port
            if (pr.get(self.sg.RULE_FROM_PORT) is None and
                    pr.get(self.sg.RULE_TO_PORT) is None):
                rule[self.sg.RULE_CIDR_IP] = None
            else:
                rule[self.sg.RULE_CIDR_IP] = pr.get(self.sg.RULE_CIDR_IP)
            # Neutron understands both names and ids
            rule[self.sg.RULE_SOURCE_SECURITY_GROUP_ID] = (
                pr.get(self.sg.RULE_SOURCE_SECURITY_GROUP_ID) or
                pr.get(self.sg.RULE_SOURCE_SECURITY_GROUP_NAME)
            )
            rule.pop(self.sg.RULE_SOURCE_SECURITY_GROUP_NAME)
            rules.append(rule)
        return rules

    def create(self):
        sec = self.client.create_security_group({'security_group': {
            'name': self.sg.physical_resource_name(),
            'description': self.sg.properties[self.sg.GROUP_DESCRIPTION]}
        })['security_group']

        self.sg.resource_id_set(sec['id'])
        self.delete_default_egress_rules(sec)
        if self.sg.properties[self.sg.SECURITY_GROUP_INGRESS]:
            rules_in = self._prop_rules_to_common(
                self.sg.properties, self.sg.SECURITY_GROUP_INGRESS)
            for rule in rules_in:
                rule['direction'] = 'ingress'
                self.create_rule(rule)

        if self.sg.properties[self.sg.SECURITY_GROUP_EGRESS]:
            rules_e = self._prop_rules_to_common(
                self.sg.properties, self.sg.SECURITY_GROUP_EGRESS)
            for rule in rules_e:
                rule['direction'] = 'egress'
                self.create_rule(rule)

    def create_rule(self, rule):
        try:
            self.client.create_security_group_rule({
                'security_group_rule':
                self._convert_to_neutron_rule(rule)
            })
        except Exception as ex:
            # ignore error if the group already exists
            if not self.plugin.is_conflict(ex):
                raise

    def delete(self):
        if self.sg.resource_id is not None:
            try:
                sec = self.client.show_security_group(
                    self.sg.resource_id)['security_group']
            except Exception as ex:
                self.plugin.ignore_not_found(ex)
            else:
                for rule in sec['security_group_rules']:
                    self.delete_rule(rule['id'])

                with self.plugin.ignore_not_found:
                    self.client.delete_security_group(self.sg.resource_id)

    def delete_rule(self, rule_id):
        with self.plugin.ignore_not_found:
            self.client.delete_security_group_rule(rule_id)

    def delete_default_egress_rules(self, sec):
        """Delete the default rules which allow all egress traffic."""
        if self.sg.properties[self.sg.SECURITY_GROUP_EGRESS]:
            for rule in sec['security_group_rules']:
                if rule['direction'] == 'egress':
                    self.client.delete_security_group_rule(rule['id'])

    def update(self, props):
        sec = self.client.show_security_group(
            self.sg.resource_id)['security_group']

        existing = self._res_rules_to_common(
            sec['security_group_rules'])
        updated = {}
        updated[self.sg.SECURITY_GROUP_EGRESS
                ] = self._prop_rules_to_common(
                    props, self.sg.SECURITY_GROUP_EGRESS)

        updated[self.sg.SECURITY_GROUP_INGRESS
                ] = self._prop_rules_to_common(
                    props, self.sg.SECURITY_GROUP_INGRESS)
        ids, new = self.diff_rules(existing, updated)
        for id in ids:
            self.delete_rule(id)
        for rule in new:
            self.create_rule(rule)

    def diff_rules(self, existing, updated):
        for rule in updated[self.sg.SECURITY_GROUP_EGRESS]:
            rule['direction'] = 'egress'
        for rule in updated[self.sg.SECURITY_GROUP_INGRESS]:
            rule['direction'] = 'ingress'
        updated_rules = list(six.itervalues(updated))
        updated_all = updated_rules[0] + updated_rules[1]
        ids_to_delete = [id for id, rule in existing.items()
                         if rule not in updated_all]
        rules_to_create = [rule for rule in updated_all
                           if rule not in six.itervalues(existing)]
        return ids_to_delete, rules_to_create


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
            ),
            update_allowed=True
        ),
        SECURITY_GROUP_EGRESS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of security group egress rules.'),
                schema=_rule_schema,
            ),
            update_allowed=True
        ),
    }

    def handle_create(self):
        NeutronSecurityGroup(self).create()

    def handle_delete(self):
        NeutronSecurityGroup(self).delete()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if (self.SECURITY_GROUP_INGRESS in prop_diff or
                self.SECURITY_GROUP_EGRESS in prop_diff):
            props = json_snippet.properties(self.properties_schema,
                                            self.context)
            NeutronSecurityGroup(self).update(props)


class SecurityGroupNotFound(exception.HeatException):
    msg_fmt = _('Security Group "%(group_name)s" not found')


def resource_mapping():
    return {
        'AWS::EC2::SecurityGroup': SecurityGroup,
    }
