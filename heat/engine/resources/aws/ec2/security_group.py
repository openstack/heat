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

import abc

import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import properties
from heat.engine import resource


@six.add_metaclass(abc.ABCMeta)
class BaseSecurityGroup(object):

    def __init__(self, sg):
        self.sg = sg

    @abc.abstractmethod
    def create(self):
        return

    @abc.abstractmethod
    def delete(self):
        return

    @abc.abstractmethod
    def update(self, props):
        return

    def diff_rules(self, existing, updated):
        ids_to_delete = [id for id, rule in existing.items()
                         if rule not in updated]
        rules_to_create = [rule for rule in updated
                           if rule not in six.itervalues(existing)]
        return ids_to_delete, rules_to_create


class NovaSecurityGroup(BaseSecurityGroup):

    def __init__(self, sg):
        super(NovaSecurityGroup, self).__init__(sg)
        self.client = sg.client('nova')
        self.plugin = sg.client_plugin('nova')

    def _get_rule_secgroupid_nova(self, prop):
        source_group_id = None
        if prop.get(self.sg.RULE_SOURCE_SECURITY_GROUP_ID) is not None:
            source_group_id = prop[self.sg.RULE_SOURCE_SECURITY_GROUP_ID]
        elif prop.get(self.sg.RULE_SOURCE_SECURITY_GROUP_NAME) is not None:
            rule_name = prop[self.sg.RULE_SOURCE_SECURITY_GROUP_NAME]
            for group in self.client.security_groups.list():
                if group.name == rule_name:
                    source_group_id = group.id
                    break
            else:
                raise SecurityGroupNotFound(group_name=rule_name)
        return source_group_id

    def _prop_rules_to_common(self, props, direction):
        rules = []
        for pr in props[direction]:
            rule = dict(pr)
            rule.pop(self.sg.RULE_SOURCE_SECURITY_GROUP_OWNER_ID)
            if rule[self.sg.RULE_FROM_PORT]:
                rule[self.sg.RULE_FROM_PORT] = int(
                    rule[self.sg.RULE_FROM_PORT])
            if rule[self.sg.RULE_TO_PORT]:
                rule[self.sg.RULE_TO_PORT] = int(rule[self.sg.RULE_TO_PORT])
            rule[self.sg.RULE_SOURCE_SECURITY_GROUP_ID
                 ] = self._get_rule_secgroupid_nova(rule)
            rule.pop(self.sg.RULE_SOURCE_SECURITY_GROUP_NAME)
            rules.append(rule)
        return rules

    def _res_rules_to_common(self, api_rules):
        rules = {}
        for nr in api_rules:
            rule = {}
            rule[self.sg.RULE_CIDR_IP] = nr['ip_range'].get('cidr') or None
            rule[self.sg.RULE_IP_PROTOCOL] = nr['ip_protocol']
            rule[self.sg.RULE_FROM_PORT] = nr['from_port'] or None
            rule[self.sg.RULE_TO_PORT] = nr['to_port'] or None
            # set source_group_id as id, not name
            group_name = nr['group'].get('name')
            group_id = None
            if group_name:
                for group in self.client.security_groups.list():
                    if group.name == group_name:
                        group_id = group.id
                        break
            rule[self.sg.RULE_SOURCE_SECURITY_GROUP_ID] = group_id
            rules[nr['id']] = rule
        return rules

    def create(self):
        sec = None
        groups = self.client.security_groups.list()
        for group in groups:
            if group.name == self.sg.physical_resource_name():
                sec = group
                break

        if not sec:
            sec = self.client.security_groups.create(
                self.sg.physical_resource_name(),
                self.sg.properties[self.sg.GROUP_DESCRIPTION])

        self.sg.resource_id_set(sec.id)
        if self.sg.properties[self.sg.SECURITY_GROUP_INGRESS]:
            rules = self._prop_rules_to_common(
                self.sg.properties, self.sg.SECURITY_GROUP_INGRESS)
            for rule in rules:
                self.create_rule(sec, rule)

    def create_rule(self, sec, rule):
        try:
            self.client.security_group_rules.create(
                sec.id,
                rule.get(self.sg.RULE_IP_PROTOCOL),
                rule.get(self.sg.RULE_FROM_PORT),
                rule.get(self.sg.RULE_TO_PORT),
                rule.get(self.sg.RULE_CIDR_IP),
                rule.get(self.sg.RULE_SOURCE_SECURITY_GROUP_ID))
        except Exception as ex:
            # ignore error if the group already exists
            if not (self.plugin.is_bad_request(ex) and
                    'already exists' in six.text_type(ex)):
                raise

    def delete(self):
        if self.sg.resource_id is not None:
            try:
                sec = self.client.security_groups.get(self.sg.resource_id)
            except Exception as e:
                self.plugin.ignore_not_found(e)
            else:
                for rule in sec.rules:
                    self.delete_rule(rule['id'])
                self.client.security_groups.delete(self.sg.resource_id)

    def delete_rule(self, rule_id):
        try:
            self.client.security_group_rules.delete(rule_id)
        except Exception as e:
            self.plugin.ignore_not_found(e)

    def update(self, props):
        sec = self.client.security_groups.get(self.sg.resource_id)
        existing = self._res_rules_to_common(sec.rules)
        updated = self._prop_rules_to_common(
            props, self.sg.SECURITY_GROUP_INGRESS)
        ids, new = self.diff_rules(existing, updated)
        for id in ids:
            self.delete_rule(id)
        for rule in new:
            self.create_rule(sec, rule)


class NeutronSecurityGroup(BaseSecurityGroup):

    def __init__(self, sg):
        super(NeutronSecurityGroup, self).__init__(sg)
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
        for pr in props[direction]:
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
                try:
                    self.client.delete_security_group(self.sg.resource_id)
                except Exception as ex:
                    self.plugin.ignore_not_found(ex)

    def delete_rule(self, rule_id):
        try:
            self.client.delete_security_group_rule(rule_id)
        except Exception as ex:
            self.plugin.ignore_not_found(ex)

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
        return super(NeutronSecurityGroup, self).diff_rules(existing,
                                                            updated_all)


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
        if self.is_using_neutron():
            impl = NeutronSecurityGroup
        else:
            impl = NovaSecurityGroup
        impl(self).create()

    def handle_delete(self):
        if self.is_using_neutron():
            impl = NeutronSecurityGroup
        else:
            impl = NovaSecurityGroup
        impl(self).delete()

    def get_reference_id(self):
        if self.is_using_neutron():
            return super(SecurityGroup, self).get_reference_id()
        else:
            return self.physical_resource_name()

    def validate(self):
        res = super(SecurityGroup, self).validate()
        if res:
            return res

        if (self.properties[self.SECURITY_GROUP_EGRESS] and
                not self.is_using_neutron()):
            raise exception.EgressRuleNotAllowed()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        update = False
        if (self.is_using_neutron() and (
                self.SECURITY_GROUP_INGRESS in prop_diff or
                self.SECURITY_GROUP_EGRESS in prop_diff)):
            impl = NeutronSecurityGroup
            update = True
        elif (not self.is_using_neutron() and
              self.SECURITY_GROUP_INGRESS in prop_diff):
            impl = NovaSecurityGroup
            update = True

        if update:
            props = json_snippet.properties(self.properties_schema,
                                            self.context)
            impl(self).update(props)


class SecurityGroupNotFound(exception.HeatException):
    msg_fmt = _('Security Group "%(group_name)s" not found')


def resource_mapping():
    return {
        'AWS::EC2::SecurityGroup': SecurityGroup,
    }
