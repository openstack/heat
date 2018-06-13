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

import mock

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.openstack.neutron import security_group_rule
from heat.tests import common
from heat.tests.openstack.neutron import inline_templates
from heat.tests import utils


class SecurityGroupRuleTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = security_group_rule.resource_mapping()
        self.assertEqual(mapping['OS::Neutron::SecurityGroupRule'],
                         security_group_rule.SecurityGroupRule)

    @mock.patch('heat.engine.clients.os.neutron.'
                'NeutronClientPlugin.has_extension', return_value=True)
    def _create_stack(self, ext_func,
                      tmpl=inline_templates.SECURITY_GROUP_RULE_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.sg_rule = self.stack['security_group_rule']
        self.neutron_client = mock.MagicMock()
        self.sg_rule.client = mock.MagicMock(return_value=self.neutron_client)

        self.sg_rule.client_plugin().find_resourceid_by_name_or_id = (
            mock.MagicMock(return_value='123'))

    def test_create(self):
        self._create_stack()
        self.neutron_client.create_security_group_rule.return_value = {
            'security_group_rule': {'id': '1234'}}
        expected = {
            'security_group_rule': {
                'security_group_id': u'123',
                'description': u'test description',
                'remote_group_id': u'123',
                'protocol': u'tcp',
                'port_range_min': '100',
                'direction': 'ingress',
                'ethertype': 'IPv4'
            }
        }

        self.sg_rule.handle_create()

        self.neutron_client.create_security_group_rule.assert_called_with(
            expected)

    def test_validate_conflict_props(self):
        self.patchobject(security_group_rule.SecurityGroupRule,
                         'is_service_available',
                         return_value=(True, None))

        tmpl = inline_templates.SECURITY_GROUP_RULE_TEMPLATE
        tmpl += '      remote_ip_prefix: "10.0.0.0/8"'
        self._create_stack(tmpl=tmpl)

        self.assertRaises(exception.ResourcePropertyConflict,
                          self.sg_rule.validate)

    def test_validate_max_port_less_than_min_port(self):
        self.patchobject(security_group_rule.SecurityGroupRule,
                         'is_service_available',
                         return_value=(True, None))

        tmpl = inline_templates.SECURITY_GROUP_RULE_TEMPLATE
        tmpl += '      port_range_max: 50'
        self._create_stack(tmpl=tmpl)

        self.assertRaises(exception.StackValidationFailed,
                          self.sg_rule.validate)

    def test_show_resource(self):
        self._create_stack()
        self.sg_rule.resource_id_set('1234')
        self.neutron_client.show_security_group_rule.return_value = {
            'security_group_rule': {'id': '1234'}
        }

        self.assertEqual({'id': '1234'}, self.sg_rule._show_resource())
        self.neutron_client.show_security_group_rule.assert_called_with('1234')

    def test_delete(self):
        self._create_stack()
        self.sg_rule.resource_id_set('1234')

        self.sg_rule.handle_delete()

        self.neutron_client.delete_security_group_rule.assert_called_with(
            '1234')
