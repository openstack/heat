# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""
Resources for Rackspace Auto Scale.
"""

import copy

from heat.engine import resource
from heat.db.sqlalchemy import api as db_api
from heat.common import exception

try:
    from pyrax.exceptions import Forbidden
    from pyrax.exceptions import NotFound
except ImportError:
    class Forbidden(Exception):
        """Dummy pyrax exception - only used for testing."""

    class NotFound(Exception):
        """Dummy pyrax exception - only used for testing."""
    def resource_mapping():
        return {}
else:
    def resource_mapping():
        return unprotected_resources()


class Group(resource.Resource):
    """Represents a scaling group."""

    # pyrax differs drastically from the actual Auto Scale API. We'll prefer
    # the true API here, but since pyrax doesn't support the full flexibility
    # of the API, we'll have to restrict what users can provide.

    network_schema = {
        'uuid': {
            'Type': 'String',
            'Required': True,
            'Description': _("UUID of network to attach to.")}}

    server_args_schema = {
        'name': {
            'Type': 'String',
            'Required': True,
            'Description': _("Server name.")},
        'flavorRef': {
            'Type': 'String',
            'Required': True,
            'Description': _("Flavor ID.")},
        'imageRef': {
            'Type': 'String',
            'Required': True,
            'Description': _("Image ID.")},
        'metadata': {
            'Type': 'Map',
            'Description': _("Metadata key and value pairs.")},
        'personality': {
            'Type': 'Map',
            'Description': _("File path and contents.")},
        'networks': {
            'Type': 'Map',
            'Schema': network_schema,
            'Description': _(
                "Networks to attach to. If unspecified, the instance will be "
                "attached to the public Internet and private ServiceNet "
                "networks.")},
        # technically maps to OS-DCF:diskConfig
        'diskConfig': {
            'Type': 'String',
            'AllowedValues': ['AUTO', 'MANUAL'],
            'Description': _(
                "Configuration specifying the partition layout. "
                "AUTO to create a partition utilizing the entire disk, and "
                "MANUAL to create a partition matching the source image.")},
        'key_name': {
            'Type': 'String',
            'Description': _(
                "Name of a previously created SSH keypair to allow key-based "
                "authentication to the server."),
        }
    }

    load_balancers_schema = {
        'loadBalancerId': {
            'Type': 'String',
            'Required': True,
            'Description': _("ID of the load balancer.")},
        'port': {
            'Type': 'Number',
            'Required': True,
            'Description': _("Server port to connect the load balancer to.")}
    }

    launch_config_args_schema = {
        'server': {
            'Type': 'Map',
            'Required': True,
            'Description': _("Server creation arguments, as accepted by the "
                             "Cloud Servers server creation API."),
            'Schema': server_args_schema},
        'loadBalancers': {
            'Type': 'List',
            'Required': False,
            'Description': _(
                "List of load balancers to hook the server up to. If not "
                "specified, no load balancing will be configured."),
            'Schema': {'Type': 'Map', 'Schema': load_balancers_schema}},
    }

    launch_configuration_schema = {
        'type': {
            'Type': 'String',
            'Required': True,
            'AllowedValues': ['launch_server'],
            'Description': _(
                "Launch configuration method. "
                "Only launch_server is currently supported.")},
        'args': {
            'Type': 'Map',
            'Required': True,
            'Schema': launch_config_args_schema,
            'Description': _("Type-specific server launching arguments.")},
    }

    group_configuration_schema = {
        'name': {
            'Type': 'String',
            'Required': True,
            'Description': _("Name of the scaling group.")},
        'cooldown': {
            'Type': 'Number',
            'Required': True,
            'Description': _(
                "Number of seconds after capacity changes during which "
                "further capacity changes are disabled.")},
        'minEntities': {
            'Type': 'Number',
            'Required': True,
            'Description': _(
                "Minimum number of entities in this scaling group.")},
        'maxEntities': {
            'Type': 'Number',
            'Required': True,
            'Description': _(
                "Maximum number of entities in this scaling group.")},
        'metadata': {
            'Type': 'Map',
            'Description': _(
                "Arbitrary key/value metadata to associate with this group.")},
    }

    # properties are identical to the API POST /groups.
    properties_schema = {
        'groupConfiguration': {
            'Type': 'Map',
            'Required': True,
            'Schema': group_configuration_schema,
            'Description': _("Group configuration.")},
        'launchConfiguration': {
            'Type': 'Map',
            'Required': True,
            'Schema': launch_configuration_schema,
            'Description': _("Launch configuration.")},
        # We don't allow scaling policies to be specified here, despite the
        # fact that the API supports it. Users should use the ScalingPolicy
        # resource.
    }

    update_allowed_keys = ('Properties',)
    # Everything can be changed.
    update_allowed_properties = ('groupConfiguration', 'launchConfiguration')

    def _get_group_config_args(self, groupconf):
        """Get the groupConfiguration-related pyrax arguments."""
        return dict(
            name=groupconf['name'],
            cooldown=groupconf['cooldown'],
            min_entities=groupconf['minEntities'],
            max_entities=groupconf['maxEntities'],
            metadata=groupconf.get('metadata', None))

    def _get_launch_config_args(self, launchconf):
        """Get the launchConfiguration-related pyrax arguments."""
        lcargs = launchconf['args']
        server_args = lcargs['server']
        lbs = copy.deepcopy(lcargs.get('loadBalancers'))
        if lbs:
            for lb in lbs:
                lb['loadBalancerId'] = int(lb['loadBalancerId'])
        return dict(
            launch_config_type=launchconf['type'],
            server_name=server_args['name'],
            image=server_args['imageRef'],
            flavor=server_args['flavorRef'],
            disk_config=server_args.get('diskConfig'),
            metadata=server_args.get('metadata'),
            personality=server_args.get('personality'),
            networks=server_args.get('networks'),
            load_balancers=lbs,
            key_name=server_args.get('key_name'),
        )

    def _get_create_args(self):
        """Get pyrax-style arguments for creating a scaling group."""
        args = self._get_group_config_args(
            self.properties['groupConfiguration'])
        args['group_metadata'] = args.pop('metadata')
        args.update(self._get_launch_config_args(
            self.properties['launchConfiguration']))
        return args

    def handle_create(self):
        """
        Create the autoscaling group and set the resulting group's ID as the
        resource_id.
        """
        asclient = self.stack.clients.auto_scale()
        group = asclient.create(**self._get_create_args())
        self.resource_id_set(str(group.id))

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """
        Update the group configuration and the launch configuration.
        """
        asclient = self.stack.clients.auto_scale()
        if 'groupConfiguration' in prop_diff:
            args = self._get_group_config_args(prop_diff['groupConfiguration'])
            asclient.replace(self.resource_id, **args)
        if 'launchConfiguration' in prop_diff:
            args = self._get_launch_config_args(
                prop_diff['launchConfiguration'])
            asclient.replace_launch_config(self.resource_id, **args)

    def handle_delete(self):
        """
        Delete the scaling group.

        Since Auto Scale doesn't allow deleting a group until all its servers
        are gone, we must set the minEntities and maxEntities of the group to 0
        and then keep trying the delete until Auto Scale has deleted all the
        servers and the delete will succeed.
        """
        if self.resource_id is None:
            return
        asclient = self.stack.clients.auto_scale()
        args = self._get_group_config_args(
            self.properties['groupConfiguration'])
        args['min_entities'] = 0
        args['max_entities'] = 0
        try:
            asclient.replace(self.resource_id, **args)
        except NotFound:
            pass

    def check_delete_complete(self, result):
        """Try the delete operation until it succeeds."""
        if self.resource_id is None:
            return True
        try:
            self.stack.clients.auto_scale().delete(self.resource_id)
        except Forbidden:
            return False
        except NotFound:
            return True
        else:
            return True


class ScalingPolicy(resource.Resource):
    """Represents a Rackspace Auto Scale scaling policy."""
    properties_schema = {
        # group isn't in the post body, but it's in the URL to post to.
        'group': {
            'Type': 'String',
            'Required': True,
            'Description': _("Scaling group ID that this policy "
                             "belongs to.")},
        'name': {
            'Type': 'String',
            'Required': True,
            'Description': _("Name of this scaling policy.")},
        'change': {
            'Type': 'Number',
            'Required': False,
            'Description': _(
                "Amount to add to or remove from current number of instances. "
                "Incompatible with changePercent and desiredCapacity.")},
        'changePercent': {
            'Type': 'Number',
            'Required': False,
            'Description': _(
                "Percentage-based change to add or remove from current number "
                "of instances. Incompatible with change and desiredCapacity.")
        },
        'desiredCapacity': {
            'Type': 'Number',
            'Required': False,
            'Description': _(
                "Absolute number to set the number of instances to. "
                "Incompatible with change and changePercent.")},
        'cooldown': {
            'Type': 'Number',
            'Required': False,
            'Description': _(
                "Number of seconds after a policy execution during which "
                "further executions are disabled.")},
        'type': {
            'Type': 'String',
            'Required': True,
            'AllowedValues': ['webhook', 'schedule', 'cloud_monitoring'],
            'Description': _(
                "Type of this scaling policy. Specifies how the policy is "
                "executed.")},
        'args': {
            'Type': 'Map',
            'Required': False,
            'Description': _("Type-specific arguments for the policy.")},
    }

    update_allowed_keys = ('Properties',)
    # Everything other than group can be changed.
    update_allowed_properties = (
        'name', 'change', 'changePercent', 'desiredCapacity', 'cooldown',
        'type', 'args')

    def _get_args(self, properties):
        """Get pyrax-style create arguments for scaling policies."""
        args = dict(
            scaling_group=properties['group'],
            name=properties['name'],
            policy_type=properties['type'],
            cooldown=properties['cooldown'],
        )
        if properties.get('change') is not None:
            args['change'] = properties['change']
        elif properties.get('changePercent') is not None:
            args['change'] = properties['changePercent']
            args['is_percent'] = True
        elif properties.get('desiredCapacity') is not None:
            args['desired_capacity'] = properties['desiredCapacity']
        if properties.get('args') is not None:
            args['args'] = properties['args']
        return args

    def handle_create(self):
        """
        Create the scaling policy, and initialize the resource ID to
        {group_id}:{policy_id}.
        """
        asclient = self.stack.clients.auto_scale()
        args = self._get_args(self.properties)
        policy = asclient.add_policy(**args)
        resource_id = '%s:%s' % (self.properties['group'], policy.id)
        self.resource_id_set(resource_id)

    def _get_policy_id(self):
        return self.resource_id.split(':', 1)[1]

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        asclient = self.stack.clients.auto_scale()
        args = self._get_args(tmpl_diff['Properties'])
        args['policy'] = self._get_policy_id()
        asclient.replace_policy(**args)

    def handle_delete(self):
        """Delete the policy if it exists."""
        asclient = self.stack.clients.auto_scale()
        if self.resource_id is None:
            return
        policy_id = self._get_policy_id()
        try:
            asclient.delete_policy(self.properties['group'], policy_id)
        except NotFound:
            pass


class WebHook(resource.Resource):
    """
    Represents a Rackspace AutoScale webhook.

    Exposes the URLs of the webhook as attributes.
    """
    properties_schema = {
        'policy': {
            'Type': 'String',
            'Required': True,
            'Description': _(
                "The policy that this webhook should apply to, in "
                "{group_id}:{policy_id} format. Generally a Ref to a Policy "
                "resource.")},
        'name': {
            'Type': 'String',
            'Required': True,
            'Description': _("The name of this webhook.")},
        'metadata': {
            'Type': 'Map',
            'Required': False,
            'Description': _("Arbitrary key/value metadata for this webhook."),
        },
    }

    update_allowed_keys = ('Properties',)
    # Everything other than policy can be changed.
    update_allowed_properties = ('name', 'metadata')

    attributes_schema = {
        'executeUrl': _(
            "The url for executing the webhook (requires auth)."),
        'capabilityUrl': _(
            "The url for executing the webhook (doesn't require auth)."),
    }

    def _get_args(self, props):
        group_id, policy_id = props['policy'].split(':', 1)
        return dict(
            name=props['name'],
            scaling_group=group_id,
            policy=policy_id,
            metadata=props.get('metadata'))

    def handle_create(self):
        asclient = self.stack.clients.auto_scale()
        args = self._get_args(self.properties)
        webhook = asclient.add_webhook(**args)
        self.resource_id_set(webhook.id)

        for link in webhook.links:
            rel_to_key = {'self': 'executeUrl',
                          'capability': 'capabilityUrl'}
            key = rel_to_key.get(link['rel'])
            if key is not None:
                url = link['href'].encode('utf-8')
                db_api.resource_data_set(self, key, url)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        asclient = self.stack.clients.auto_scale()
        args = self._get_args(json_snippet['Properties'])
        args['webhook'] = self.resource_id
        asclient.replace_webhook(**args)

    def _resolve_attribute(self, key):
        try:
            return db_api.resource_data_get(self, key).decode('utf-8')
        except exception.NotFound:
            return None

    def handle_delete(self):
        if self.resource_id is None:
            return
        asclient = self.stack.clients.auto_scale()
        group_id, policy_id = self.properties['policy'].split(':', 1)
        try:
            asclient.delete_webhook(group_id, policy_id, self.resource_id)
        except NotFound:
            pass


def unprotected_resources():
    return {
        'Rackspace::AutoScale::Group': Group,
        'Rackspace::AutoScale::ScalingPolicy': ScalingPolicy,
        'Rackspace::AutoScale::WebHook': WebHook
    }
