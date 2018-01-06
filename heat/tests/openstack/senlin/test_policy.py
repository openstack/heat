#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import copy
import mock

from openstack import exceptions
from oslo_config import cfg

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import senlin
from heat.engine.resources.openstack.senlin import policy
from heat.engine import scheduler
from heat.engine import template
from heat.tests import common
from heat.tests import utils


policy_stack_template = """
heat_template_version: 2016-04-08
description: Senlin Policy Template
resources:
  senlin-policy:
    type: OS::Senlin::Policy
    properties:
      name: SenlinPolicy
      type: senlin.policy.deletion-1.0
      properties:
        criteria: OLDEST_FIRST
      bindings:
        - cluster: c1
"""

policy_spec = {
    'type': 'senlin.policy.deletion',
    'version': '1.0',
    'properties': {
        'criteria': 'OLDEST_FIRST'
    }
}


class FakePolicy(object):
    def __init__(self, id='some_id', spec=None):
        self.id = id
        self.name = "SenlinPolicy"

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
        }


class SenlinPolicyTest(common.HeatTestCase):
    def setUp(self):
        super(SenlinPolicyTest, self).setUp()
        self.patchobject(senlin.ClusterConstraint, 'validate',
                         return_value=True)
        self.patchobject(senlin.PolicyTypeConstraint, 'validate',
                         return_value=True)
        self.senlin_mock = mock.MagicMock()
        self.senlin_mock.get_cluster.return_value = mock.Mock(
            id='c1_id')
        self.patchobject(policy.Policy, 'client',
                         return_value=self.senlin_mock)
        self.patchobject(senlin.SenlinClientPlugin, 'client',
                         return_value=self.senlin_mock)
        self.fake_p = FakePolicy()
        self.t = template_format.parse(policy_stack_template)

    def _init_policy(self, template):
        self.stack = utils.parse_stack(template)
        policy = self.stack['senlin-policy']
        return policy

    def _create_policy(self, template):
        policy = self._init_policy(template)
        self.senlin_mock.create_policy.return_value = self.fake_p
        self.senlin_mock.cluster_attach_policy.return_value = {
            'action': 'fake_action'}
        self.senlin_mock.get_action.return_value = mock.Mock(
            status='SUCCEEDED')
        scheduler.TaskRunner(policy.create)()
        self.assertEqual((policy.CREATE, policy.COMPLETE),
                         policy.state)
        self.assertEqual(self.fake_p.id, policy.resource_id)
        self.senlin_mock.cluster_attach_policy.assert_called_once_with(
            'c1_id', policy.resource_id, enabled=True)
        self.senlin_mock.get_action.assert_called_once_with('fake_action')
        return policy

    def test_policy_create(self):
        self._create_policy(self.t)
        expect_kwargs = {
            'name': 'SenlinPolicy',
            'spec': policy_spec
        }
        self.senlin_mock.create_policy.assert_called_once_with(
            **expect_kwargs)

    def test_policy_create_fail(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        policy = self._init_policy(self.t)
        self.senlin_mock.create_policy.return_value = self.fake_p
        self.senlin_mock.cluster_attach_policy.return_value = {
            'action': 'fake_action'}
        self.senlin_mock.get_action.return_value = mock.Mock(
            status='FAILED', status_reason='oops',
            action='CLUSTER_ATTACH_POLICY')
        create_task = scheduler.TaskRunner(policy.create)
        self.assertRaises(exception.ResourceFailure, create_task)
        self.assertEqual((policy.CREATE, policy.FAILED),
                         policy.state)
        err_msg = ('ResourceInError: resources.senlin-policy: Went to status '
                   'FAILED due to "Failed to execute CLUSTER_ATTACH_POLICY '
                   'for c1_id: oops"')
        self.assertEqual(err_msg, policy.status_reason)

    def test_policy_delete_not_found(self):
        self.senlin_mock.cluster_detach_policy.return_value = {
            'action': 'fake_action'}
        policy = self._create_policy(self.t)
        self.senlin_mock.get_policy.side_effect = [
            exceptions.ResourceNotFound('SenlinPolicy'),
        ]
        scheduler.TaskRunner(policy.delete)()
        self.senlin_mock.cluster_detach_policy.assert_called_once_with(
            'c1_id', policy.resource_id)
        self.senlin_mock.delete_policy.assert_called_once_with(
            policy.resource_id)

    def test_policy_delete_not_attached(self):
        policy = self._create_policy(self.t)
        self.senlin_mock.get_policy.side_effect = [
            exceptions.ResourceNotFound('SenlinPolicy'),
        ]
        self.senlin_mock.cluster_detach_policy.side_effect = [
            exceptions.HttpException(http_status=400),
        ]
        scheduler.TaskRunner(policy.delete)()
        self.senlin_mock.cluster_detach_policy.assert_called_once_with(
            'c1_id', policy.resource_id)
        self.senlin_mock.delete_policy.assert_called_once_with(
            policy.resource_id)

    def test_policy_update(self):
        policy = self._create_policy(self.t)
        # Mock translate rules
        self.senlin_mock.get_cluster.side_effect = [
            mock.Mock(id='c2_id'),
            mock.Mock(id='c1_id'),
            mock.Mock(id='c2_id'),
        ]
        new_t = copy.deepcopy(self.t)
        props = new_t['resources']['senlin-policy']['properties']
        props['bindings'] = [{'cluster': 'c2'}]
        props['name'] = 'new_name'
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_cluster = rsrc_defns['senlin-policy']
        self.senlin_mock.cluster_attach_policy.return_value = {
            'action': 'fake_action1'}
        self.senlin_mock.cluster_detach_policy.return_value = {
            'action': 'fake_action2'}
        self.senlin_mock.get_policy.return_value = self.fake_p
        scheduler.TaskRunner(policy.update, new_cluster)()
        self.assertEqual((policy.UPDATE, policy.COMPLETE), policy.state)
        self.senlin_mock.update_policy.assert_called_once_with(
            self.fake_p, name='new_name')
        self.senlin_mock.cluster_detach_policy.assert_called_once_with(
            'c1_id', policy.resource_id)
        self.senlin_mock.cluster_attach_policy.assert_called_with(
            'c2_id', policy.resource_id, enabled=True)

    def test_policy_resolve_attribute(self):
        excepted_show = {
            'id': 'some_id',
            'name': 'SenlinPolicy',
        }
        policy = self._create_policy(self.t)
        self.senlin_mock.get_policy.return_value = FakePolicy()
        self.assertEqual(excepted_show, policy._show_resource())
