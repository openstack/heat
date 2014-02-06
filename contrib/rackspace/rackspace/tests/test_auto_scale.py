
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

import copy
import itertools

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine import resource
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils

from ..resources import auto_scale  # noqa


class FakeScalingGroup(object):
    """A fake implementation of pyrax's ScalingGroup object."""
    def __init__(self, id, **kwargs):
        self.id = id
        self.kwargs = kwargs


class FakeScalePolicy(object):
    """A fake implementation of pyrax's AutoScalePolicy object."""
    def __init__(self, id, **kwargs):
        self.id = id
        self.kwargs = kwargs


class FakeWebHook(object):
    """A fake implementation of pyrax's AutoScaleWebhook object."""
    def __init__(self, id, **kwargs):
        self.id = id
        self.kwargs = kwargs
        self.links = [
            {'rel': 'self', 'href': 'self-url'},
            {'rel': 'capability', 'href': 'capability-url'}]


class FakeAutoScale(object):
    """A fake implementation of pyrax's autoscale client."""

    def __init__(self):
        self.groups = {}
        self.policies = {}
        self.webhooks = {}
        self.group_counter = itertools.count()
        self.policy_counter = itertools.count()
        self.webhook_counter = itertools.count()

    def create(self, **kwargs):
        """Create a scaling group."""
        new_id = str(self.group_counter.next())
        fsg = FakeScalingGroup(new_id, **kwargs)
        self.groups[new_id] = fsg
        return fsg

    def _check_args(self, kwargs, allowed):
        for parameter in kwargs:
            if parameter not in allowed:
                raise TypeError("unexpected argument %r" % (parameter,))

    def _get_group(self, id):
        if id not in self.groups:
            raise auto_scale.NotFound("Group %s not found!" % (id,))
        return self.groups[id]

    def _get_policy(self, id):
        if id not in self.policies:
            raise auto_scale.NotFound("Policy %s not found!" % (id,))
        return self.policies[id]

    def _get_webhook(self, webhook_id):
        if webhook_id not in self.webhooks:
            raise auto_scale.NotFound(
                "Webhook %s doesn't exist!" % (webhook_id,))
        return self.webhooks[webhook_id]

    def replace(self, group_id, **kwargs):
        """Update the groupConfiguration section of a scaling group."""
        allowed = ['name', 'cooldown',
                   'min_entities', 'max_entities', 'metadata']
        self._check_args(kwargs, allowed)
        self._get_group(group_id).kwargs = kwargs

    def replace_launch_config(self, group_id, **kwargs):
        """Update the launch configuration on a scaling group."""
        allowed = ['launch_config_type', 'server_name', 'image', 'flavor',
                   'disk_config', 'metadata', 'personality', 'networks',
                   'load_balancers', 'key_name']
        self._check_args(kwargs, allowed)
        self._get_group(group_id).kwargs = kwargs

    def delete(self, group_id):
        """Delete the group, if the min entities and max entities are 0."""
        group = self._get_group(group_id)
        if (group.kwargs['min_entities'] > 0
                or group.kwargs['max_entities'] > 0):
            raise Exception("Can't delete yet!")
        del self.groups[group_id]

    def add_policy(self, **kwargs):
        """Create and store a FakeScalePolicy."""
        allowed = [
            'scaling_group', 'name', 'policy_type', 'cooldown', 'change',
            'is_percent', 'desired_capacity', 'args']
        self._check_args(kwargs, allowed)
        policy_id = str(self.policy_counter.next())
        policy = FakeScalePolicy(policy_id, **kwargs)
        self.policies[policy_id] = policy
        return policy

    def replace_policy(self, scaling_group, policy, **kwargs):
        allowed = [
            'name', 'policy_type', 'cooldown',
            'change', 'is_percent', 'desired_capacity', 'args']
        self._check_args(kwargs, allowed)
        policy = self._get_policy(policy)
        assert policy.kwargs['scaling_group'] == scaling_group
        kwargs['scaling_group'] = scaling_group
        policy.kwargs = kwargs

    def add_webhook(self, **kwargs):
        """Create and store a FakeWebHook."""
        allowed = ['scaling_group', 'policy', 'name', 'metadata']
        self._check_args(kwargs, allowed)
        webhook_id = str(self.webhook_counter.next())
        webhook = FakeWebHook(webhook_id, **kwargs)
        self.webhooks[webhook_id] = webhook
        return webhook

    def delete_policy(self, scaling_group, policy):
        """Delete a policy, if it exists."""
        if policy not in self.policies:
            raise auto_scale.NotFound("Policy %s doesn't exist!" % (policy,))
        assert self.policies[policy].kwargs['scaling_group'] == scaling_group
        del self.policies[policy]

    def delete_webhook(self, scaling_group, policy, webhook_id):
        """Delete a webhook, if it exists."""
        webhook = self._get_webhook(webhook_id)
        assert webhook.kwargs['scaling_group'] == scaling_group
        assert webhook.kwargs['policy'] == policy
        del self.webhooks[webhook_id]

    def replace_webhook(self, scaling_group, policy, webhook,
                        name=None, metadata=None):
        webhook = self._get_webhook(webhook)
        assert webhook.kwargs['scaling_group'] == scaling_group
        assert webhook.kwargs['policy'] == policy
        webhook.kwargs['name'] = name
        webhook.kwargs['metadata'] = metadata


class ScalingGroupTest(HeatTestCase):

    group_template = template_format.parse('''
    HeatTemplateFormatVersion: "2012-12-12"
    Description: "Rackspace Auto Scale"
    Parameters: {}
    Resources:
        my_group:
            Type: Rackspace::AutoScale::Group
            Properties:
                groupConfiguration:
                    name: "My Group"
                    cooldown: 60
                    minEntities: 1
                    maxEntities: 25
                    metadata:
                        group: metadata
                launchConfiguration:
                    type: "launch_server"
                    args:
                        server:
                            name: autoscaled-server
                            flavorRef: flavor-ref
                            imageRef: image-ref
                            key_name: my-key
                            metadata:
                                server: metadata
                            networks:
                                - uuid: "00000000-0000-0000-0000-000000000000"
                                - uuid: "11111111-1111-1111-1111-111111111111"
    ''')

    def setUp(self):
        super(ScalingGroupTest, self).setUp()
        utils.setup_dummy_db()
        for res_name, res_class in auto_scale.resource_mapping().items():
            resource._register_class(res_name, res_class)
        self.fake_auto_scale = FakeAutoScale()
        self.patch(clients.OpenStackClients,
                   'auto_scale', lambda resource: self.fake_auto_scale)

    def _setup_test_stack(self):
        self.stack = utils.parse_stack(self.group_template)
        self.stack.create()
        self.assertEqual(
            ('CREATE', 'COMPLETE'), self.stack.state,
            self.stack.status_reason)

    def test_group_create(self):
        """
        Creating a group passes all the correct arguments to pyrax and saves
        the group ID as the resource ID.
        """
        self._setup_test_stack()
        self.assertEqual(1, len(self.fake_auto_scale.groups))
        self.assertEqual(
            {
                'cooldown': 60,
                'disk_config': None,
                'flavor': 'flavor-ref',
                'image': 'image-ref',
                'launch_config_type': 'launch_server',
                'load_balancers': None,
                'key_name': "my-key",
                'max_entities': 25,
                'group_metadata': {'group': 'metadata'},
                'metadata': {'server': 'metadata'},
                'min_entities': 1,
                'name': 'My Group',
                'networks': [{'uuid': '00000000-0000-0000-0000-000000000000'},
                             {'uuid': '11111111-1111-1111-1111-111111111111'}],
                'personality': None,
                'server_name': u'autoscaled-server'},
            self.fake_auto_scale.groups['0'].kwargs)

        resource = self.stack['my_group']
        self.assertEqual('0', resource.FnGetRefId())

    def test_update_group_config(self):
        """
        Updating the groupConfiguration section in a template results in a
        pyrax call to update the group configuration.
        """
        self._setup_test_stack()

        resource = self.stack['my_group']
        new_template = copy.deepcopy(resource.parsed_template())
        new_template['Properties']['groupConfiguration']['minEntities'] = 5
        scheduler.TaskRunner(resource.update, new_template)()

        self.assertEqual(1, len(self.fake_auto_scale.groups))
        self.assertEqual(
            5, self.fake_auto_scale.groups['0'].kwargs['min_entities'])

    def test_update_launch_config(self):
        """
        Updating the launchConfigresults section in a template results in a
        pyrax call to update the launch configuration.
        """
        self._setup_test_stack()

        resource = self.stack['my_group']
        new_template = copy.deepcopy(resource.parsed_template())
        lcargs = new_template['Properties']['launchConfiguration']['args']
        lcargs['loadBalancers'] = [{'loadBalancerId': '1', 'port': 80}]
        scheduler.TaskRunner(resource.update, new_template)()

        self.assertEqual(1, len(self.fake_auto_scale.groups))
        self.assertEqual(
            [{'loadBalancerId': 1, 'port': 80}],
            self.fake_auto_scale.groups['0'].kwargs['load_balancers'])

    def test_delete(self):
        """
        Deleting a ScalingGroup resource invokes the pyrax API to delete it.
        """
        self._setup_test_stack()
        resource = self.stack['my_group']
        scheduler.TaskRunner(resource.delete)()
        self.assertEqual({}, self.fake_auto_scale.groups)

    def test_delete_without_backing_group(self):
        """
        If no backing scaling group exists, resource deletion silently
        succeeds.
        """
        self._setup_test_stack()
        resource = self.stack['my_group']
        del self.fake_auto_scale.groups['0']
        scheduler.TaskRunner(resource.delete)()
        self.assertEqual({}, self.fake_auto_scale.groups)

    def test_delete_waits_for_server_deletion(self):
        """
        The delete operation may fail until the servers are really gone; the
        resource retries until success.
        """
        self._setup_test_stack()
        delete_counter = itertools.count()

        def delete(group_id):
            count = delete_counter.next()
            if count < 3:
                raise auto_scale.Forbidden("Not empty!")

        self.patch(self.fake_auto_scale, 'delete', delete)
        resource = self.stack['my_group']
        scheduler.TaskRunner(resource.delete)()
        # It really called delete until it succeeded:
        self.assertEqual(4, delete_counter.next())

    def test_delete_blows_up_on_other_errors(self):
        """
        Only the Forbidden (403) error is honored as an indicator of pending
        deletion; other errors cause deletion to fail.
        """
        self._setup_test_stack()

        def delete(group_id):
            1 / 0

        self.patch(self.fake_auto_scale, 'delete', delete)
        resource = self.stack['my_group']
        err = self.assertRaises(
            exception.ResourceFailure, scheduler.TaskRunner(resource.delete))
        self.assertIsInstance(err.exc, ZeroDivisionError)


class PolicyTest(HeatTestCase):
    policy_template = template_format.parse('''
    HeatTemplateFormatVersion: "2012-12-12"
    Description: "Rackspace Auto Scale"
    Parameters: {}
    Resources:
        my_policy:
            Type: Rackspace::AutoScale::ScalingPolicy
            Properties:
                group: "my-group-id"
                name: "+10 on webhook"
                change: 10
                cooldown: 0
                type: "webhook"
    ''')

    def setUp(self):
        super(PolicyTest, self).setUp()
        utils.setup_dummy_db()
        for res_name, res_class in auto_scale.resource_mapping().items():
            resource._register_class(res_name, res_class)
        self.fake_auto_scale = FakeAutoScale()
        self.patch(clients.OpenStackClients,
                   'auto_scale', lambda resource: self.fake_auto_scale)

    def _setup_test_stack(self, template):
        self.stack = utils.parse_stack(template)
        self.stack.create()
        self.assertEqual(
            ('CREATE', 'COMPLETE'), self.stack.state,
            self.stack.status_reason)

    def test_create_webhook_change(self):
        """
        Creating the resource creates the scaling policy with pyrax,
        and sets the resource's ID to {group_id}:{policy_id}
        """
        self._setup_test_stack(self.policy_template)
        resource = self.stack['my_policy']
        self.assertEqual('my-group-id:0', resource.FnGetRefId())
        self.assertEqual(
            {
                'name': '+10 on webhook',
                'scaling_group': 'my-group-id',
                'change': 10,
                'cooldown': 0,
                'policy_type': 'webhook'},
            self.fake_auto_scale.policies['0'].kwargs)

    def test_webhook_change_percent(self):
        """
        When changePercent is specified, it translates to pyrax arguments
        'change' and 'is_percent'.
        """
        template = copy.deepcopy(self.policy_template)
        template['Resources']['my_policy']['Properties']['changePercent'] = 10
        del template['Resources']['my_policy']['Properties']['change']
        self._setup_test_stack(template)
        self.assertEqual(
            {
                'name': '+10 on webhook',
                'scaling_group': 'my-group-id',
                'change': 10,
                'is_percent': True,
                'cooldown': 0,
                'policy_type': 'webhook'},
            self.fake_auto_scale.policies['0'].kwargs)

    def test_webhook_desired_capacity(self):
        """
        The desiredCapacity property translates to the desired_capacity pyrax
        argument.
        """
        template = copy.deepcopy(self.policy_template)
        template['Resources']['my_policy']['Properties']['desiredCapacity'] = 1
        del template['Resources']['my_policy']['Properties']['change']
        self._setup_test_stack(template)
        self.assertEqual(
            {
                'name': '+10 on webhook',
                'scaling_group': 'my-group-id',
                'desired_capacity': 1,
                'cooldown': 0,
                'policy_type': 'webhook'},
            self.fake_auto_scale.policies['0'].kwargs)

    def test_schedule(self):
        """We can specify schedule-type policies with args."""
        template = copy.deepcopy(self.policy_template)
        props = template['Resources']['my_policy']['Properties']
        props['type'] = 'schedule'
        props['args'] = {'cron': '0 0 0 * *'}
        self._setup_test_stack(template)
        self.assertEqual(
            {
                'name': '+10 on webhook',
                'scaling_group': 'my-group-id',
                'change': 10,
                'cooldown': 0,
                'policy_type': 'schedule',
                'args': {'cron': '0 0 0 * *'}},
            self.fake_auto_scale.policies['0'].kwargs)

    def test_update(self):
        """
        Updating the resource calls the appropriate update method with pyrax.
        """
        self._setup_test_stack(self.policy_template)
        resource = self.stack['my_policy']
        template = copy.deepcopy(resource.parsed_template())
        template['Properties']['changePercent'] = 50
        del template['Properties']['change']

        scheduler.TaskRunner(resource.update, template)()
        self.assertEqual(
            {
                'name': '+10 on webhook',
                'scaling_group': 'my-group-id',
                'change': 50,
                'is_percent': True,
                'cooldown': 0,
                'policy_type': 'webhook'},
            self.fake_auto_scale.policies['0'].kwargs)

    def test_delete(self):
        """Deleting the resource deletes the policy with pyrax."""
        self._setup_test_stack(self.policy_template)
        resource = self.stack['my_policy']
        scheduler.TaskRunner(resource.delete)()
        self.assertEqual({}, self.fake_auto_scale.policies)

    def test_delete_policy_non_existent(self):
        """
        Deleting a resource for which there is no backing policy succeeds
        silently.
        """
        self._setup_test_stack(self.policy_template)
        resource = self.stack['my_policy']
        del self.fake_auto_scale.policies['0']
        scheduler.TaskRunner(resource.delete)()
        self.assertEqual({}, self.fake_auto_scale.policies)


class WebHookTest(HeatTestCase):
    webhook_template = template_format.parse('''
    HeatTemplateFormatVersion: "2012-12-12"
    Description: "Rackspace Auto Scale"
    Parameters: {}
    Resources:
        my_webhook:
            Type: Rackspace::AutoScale::WebHook
            Properties:
                policy: my-group-id:my-policy-id
                name: "exec my policy"
                metadata:
                    a: b
    ''')

    def setUp(self):
        super(WebHookTest, self).setUp()
        utils.setup_dummy_db()
        for res_name, res_class in auto_scale.resource_mapping().items():
            resource._register_class(res_name, res_class)
        self.fake_auto_scale = FakeAutoScale()
        self.patch(clients.OpenStackClients,
                   'auto_scale', lambda resource: self.fake_auto_scale)

    def _setup_test_stack(self, template):
        self.stack = utils.parse_stack(template)
        self.stack.create()
        self.assertEqual(
            ('CREATE', 'COMPLETE'), self.stack.state,
            self.stack.status_reason)

    def test_create(self):
        """Creates a webhook with pyrax and makes attributes available."""
        self._setup_test_stack(self.webhook_template)
        resource = self.stack['my_webhook']
        self.assertEqual(
            {
                'name': 'exec my policy',
                'scaling_group': 'my-group-id',
                'policy': 'my-policy-id',
                'metadata': {'a': 'b'}},
            self.fake_auto_scale.webhooks['0'].kwargs)
        self.assertEqual("self-url", resource.FnGetAtt("executeUrl"))
        self.assertEqual("capability-url", resource.FnGetAtt("capabilityUrl"))

    def test_failed_create(self):
        """When a create fails, getting the attributes returns None."""
        template = copy.deepcopy(self.webhook_template)
        template['Resources']['my_webhook']['Properties']['policy'] = 'foobar'
        self.stack = utils.parse_stack(template)
        self.stack.create()
        resource = self.stack['my_webhook']
        self.assertIsNone(resource.FnGetAtt('capabilityUrl'))

    def test_update(self):
        self._setup_test_stack(self.webhook_template)
        resource = self.stack['my_webhook']
        template = copy.deepcopy(resource.parsed_template())
        template['Properties']['metadata']['a'] = 'different!'
        template['Properties']['name'] = 'newhook'

        scheduler.TaskRunner(resource.update, template)()
        self.assertEqual(
            {
                'name': 'newhook',
                'scaling_group': 'my-group-id',
                'policy': 'my-policy-id',
                'metadata': {'a': 'different!'}},
            self.fake_auto_scale.webhooks['0'].kwargs)

    def test_delete(self):
        """Deleting the resource deletes the webhook with pyrax."""
        self._setup_test_stack(self.webhook_template)
        resource = self.stack['my_webhook']
        scheduler.TaskRunner(resource.delete)()
        self.assertEqual({}, self.fake_auto_scale.webhooks)

    def test_delete_without_backing_webhook(self):
        """
        Deleting a resource for which there is no backing webhook succeeds
        silently.
        """
        self._setup_test_stack(self.webhook_template)
        resource = self.stack['my_webhook']
        del self.fake_auto_scale.webhooks['0']
        scheduler.TaskRunner(resource.delete)()
        self.assertEqual({}, self.fake_auto_scale.webhooks)
