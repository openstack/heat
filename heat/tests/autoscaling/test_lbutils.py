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
import six

from heat.common import exception
from heat.common import template_format
from heat.engine import properties
from heat.engine import resource
from heat.scaling import lbutils
from heat.tests import common
from heat.tests import generic_resource
from heat.tests import utils

lb_stack = '''
heat_template_version: 2013-05-23
resources:
  neutron_lb_1:
    type: Mock::Neutron::LB
  neutron_lb_2:
    type: Mock::Neutron::LB
  aws_lb_1:
    type: Mock::AWS::LB
  aws_lb_2:
    type: Mock::AWS::LB
  non_lb:
    type: Mock::Not::LB
'''


class MockedNeutronLB(generic_resource.GenericResource):
    properties_schema = {
        'members': properties.Schema(
            properties.Schema.LIST,
            update_allowed=True)
    }

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        return


class MockedAWSLB(generic_resource.GenericResource):
    properties_schema = {
        'Instances': properties.Schema(
            properties.Schema.LIST,
            update_allowed=True)
    }

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        return


class LBUtilsTest(common.HeatTestCase):
    # need to mock a group so that group_utils.get_member_refids will work
    # load_balancers is a dict of load_balancer objects, where each lb has
    # properties for checking

    def setUp(self):
        super(LBUtilsTest, self).setUp()
        resource._register_class('Mock::Neutron::LB', MockedNeutronLB)
        resource._register_class('Mock::AWS::LB', MockedAWSLB)
        resource._register_class('Mock::Not::LB',
                                 generic_resource.GenericResource)

        t = template_format.parse(lb_stack)
        self.stack = utils.parse_stack(t)

    def test_reload_aws_lb(self):
        id_list = ['ID1', 'ID2', 'ID3']

        lb1 = self.stack['aws_lb_1']
        lb2 = self.stack['aws_lb_2']
        lb1.action = mock.Mock(return_value=lb1.CREATE)
        lb2.action = mock.Mock(return_value=lb2.CREATE)
        lb1.handle_update = mock.Mock()
        lb2.handle_update = mock.Mock()
        prop_diff = {'Instances': id_list}

        lbutils.reconfigure_loadbalancers([lb1, lb2], id_list)

        # For verification's purpose, we just check the prop_diff
        lb1.handle_update.assert_called_with(mock.ANY, mock.ANY,
                                             prop_diff)
        lb2.handle_update.assert_called_with(mock.ANY, mock.ANY,
                                             prop_diff)

    def test_reload_neutron_lb(self):
        id_list = ['ID1', 'ID2', 'ID3']

        lb1 = self.stack['neutron_lb_1']
        lb2 = self.stack['neutron_lb_2']
        lb1.action = mock.Mock(return_value=lb1.CREATE)
        lb2.action = mock.Mock(return_value=lb2.CREATE)

        lb1.handle_update = mock.Mock()
        lb2.handle_update = mock.Mock()

        prop_diff = {'members': id_list}

        lbutils.reconfigure_loadbalancers([lb1, lb2], id_list)

        # For verification's purpose, we just check the prop_diff
        lb1.handle_update.assert_called_with(mock.ANY, mock.ANY,
                                             prop_diff)
        lb2.handle_update.assert_called_with(mock.ANY, mock.ANY,
                                             prop_diff)

    def test_reload_non_lb(self):
        id_list = ['ID1', 'ID2', 'ID3']
        non_lb = self.stack['non_lb']

        error = self.assertRaises(exception.Error,
                                  lbutils.reconfigure_loadbalancers,
                                  [non_lb], id_list)
        self.assertIn("Unsupported resource 'non_lb' in LoadBalancerNames",
                      six.text_type(error))
