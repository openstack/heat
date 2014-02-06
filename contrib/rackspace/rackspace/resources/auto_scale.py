
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

from heat.common import exception
from heat.db.sqlalchemy import api as db_api
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource

try:
    from pyrax.exceptions import Forbidden
    from pyrax.exceptions import NotFound
    PYRAX_INSTALLED = True
except ImportError:
    class Forbidden(Exception):
        """Dummy pyrax exception - only used for testing."""

    class NotFound(Exception):
        """Dummy pyrax exception - only used for testing."""

    PYRAX_INSTALLED = False


class Group(resource.Resource):
    """Represents a scaling group."""

    # pyrax differs drastically from the actual Auto Scale API. We'll prefer
    # the true API here, but since pyrax doesn't support the full flexibility
    # of the API, we'll have to restrict what users can provide.

    # properties are identical to the API POST /groups.
    PROPERTIES = (
        GROUP_CONFIGURATION, LAUNCH_CONFIGURATION,
    ) = (
        'groupConfiguration', 'launchConfiguration',
    )

    _GROUP_CONFIGURATION_KEYS = (
        GROUP_CONFIGURATION_MAX_ENTITIES, GROUP_CONFIGURATION_COOLDOWN,
        GROUP_CONFIGURATION_NAME, GROUP_CONFIGURATION_MIN_ENTITIES,
        GROUP_CONFIGURATION_METADATA,
    ) = (
        'maxEntities', 'cooldown',
        'name', 'minEntities',
        'metadata',
    )

    _LAUNCH_CONFIG_KEYS = (
        LAUNCH_CONFIG_ARGS, LAUNCH_CONFIG_TYPE,
    ) = (
        'args', 'type',
    )

    _LAUNCH_CONFIG_ARGS_KEYS = (
        LAUNCH_CONFIG_ARGS_LOAD_BALANCERS,
        LAUNCH_CONFIG_ARGS_SERVER,
    ) = (
        'loadBalancers',
        'server',
    )

    _LAUNCH_CONFIG_ARGS_LOAD_BALANCER_KEYS = (
        LAUNCH_CONFIG_ARGS_LOAD_BALANCER_ID,
        LAUNCH_CONFIG_ARGS_LOAD_BALANCER_PORT,
    ) = (
        'loadBalancerId',
        'port',
    )

    _LAUNCH_CONFIG_ARGS_SERVER_KEYS = (
        LAUNCH_CONFIG_ARGS_SERVER_NAME, LAUNCH_CONFIG_ARGS_SERVER_FLAVOR_REF,
        LAUNCH_CONFIG_ARGS_SERVER_IMAGE_REF,
        LAUNCH_CONFIG_ARGS_SERVER_METADATA,
        LAUNCH_CONFIG_ARGS_SERVER_PERSONALITY,
        LAUNCH_CONFIG_ARGS_SERVER_NETWORKS,
        LAUNCH_CONFIG_ARGS_SERVER_DISK_CONFIG,
        LAUNCH_CONFIG_ARGS_SERVER_KEY_NAME,
    ) = (
        'name', 'flavorRef',
        'imageRef',
        'metadata',
        'personality',
        'networks',
        'diskConfig',  # technically maps to OS-DCF:diskConfig
        'key_name',
    )

    _LAUNCH_CONFIG_ARGS_SERVER_NETWORK_KEYS = (
        LAUNCH_CONFIG_ARGS_SERVER_NETWORK_UUID,
    ) = (
        'uuid',
    )

    _launch_configuration_args_schema = {
        LAUNCH_CONFIG_ARGS_LOAD_BALANCERS: properties.Schema(
            properties.Schema.LIST,
            _('List of load balancers to hook the '
              'server up to. If not specified, no '
              'load balancing will be configured.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    LAUNCH_CONFIG_ARGS_LOAD_BALANCER_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('ID of the load balancer.'),
                        required=True
                    ),
                    LAUNCH_CONFIG_ARGS_LOAD_BALANCER_PORT: properties.Schema(
                        properties.Schema.NUMBER,
                        _('Server port to connect the load balancer to.'),
                        required=True
                    ),
                },
            )
        ),
        LAUNCH_CONFIG_ARGS_SERVER: properties.Schema(
            properties.Schema.MAP,
            _('Server creation arguments, as accepted by the Cloud Servers '
              'server creation API.'),
            schema={
                LAUNCH_CONFIG_ARGS_SERVER_NAME: properties.Schema(
                    properties.Schema.STRING,
                    _('Server name.'),
                    required=True
                ),
                LAUNCH_CONFIG_ARGS_SERVER_FLAVOR_REF: properties.Schema(
                    properties.Schema.STRING,
                    _('Flavor ID.'),
                    required=True
                ),
                LAUNCH_CONFIG_ARGS_SERVER_IMAGE_REF: properties.Schema(
                    properties.Schema.STRING,
                    _('Image ID.'),
                    required=True
                ),
                LAUNCH_CONFIG_ARGS_SERVER_METADATA: properties.Schema(
                    properties.Schema.MAP,
                    _('Metadata key and value pairs.')
                ),
                LAUNCH_CONFIG_ARGS_SERVER_PERSONALITY: properties.Schema(
                    properties.Schema.MAP,
                    _('File path and contents.')
                ),
                LAUNCH_CONFIG_ARGS_SERVER_NETWORKS: properties.Schema(
                    properties.Schema.LIST,
                    _('Networks to attach to. If unspecified, the instance '
                      'will be attached to the public Internet and private '
                      'ServiceNet networks.'),
                    schema=properties.Schema(
                        properties.Schema.MAP,
                        schema={
                            LAUNCH_CONFIG_ARGS_SERVER_NETWORK_UUID:
                            properties.Schema(
                                properties.Schema.STRING,
                                _('UUID of network to attach to.'),
                                required=True)
                        }
                    )
                ),
                LAUNCH_CONFIG_ARGS_SERVER_DISK_CONFIG: properties.Schema(
                    properties.Schema.STRING,
                    _('Configuration specifying the partition layout. AUTO to '
                      'create a partition utilizing the entire disk, and '
                      'MANUAL to create a partition matching the source '
                      'image.'),
                    constraints=[
                        constraints.AllowedValues(['AUTO', 'MANUAL']),
                    ]
                ),
                LAUNCH_CONFIG_ARGS_SERVER_KEY_NAME: properties.Schema(
                    properties.Schema.STRING,
                    _('Name of a previously created SSH keypair to allow '
                      'key-based authentication to the server.')
                ),
            },
            required=True
        ),
    }

    properties_schema = {
        GROUP_CONFIGURATION: properties.Schema(
            properties.Schema.MAP,
            _('Group configuration.'),
            schema={
                GROUP_CONFIGURATION_MAX_ENTITIES: properties.Schema(
                    properties.Schema.NUMBER,
                    _('Maximum number of entities in this scaling group.'),
                    required=True
                ),
                GROUP_CONFIGURATION_COOLDOWN: properties.Schema(
                    properties.Schema.NUMBER,
                    _('Number of seconds after capacity changes during '
                      'which further capacity changes are disabled.'),
                    required=True
                ),
                GROUP_CONFIGURATION_NAME: properties.Schema(
                    properties.Schema.STRING,
                    _('Name of the scaling group.'),
                    required=True
                ),
                GROUP_CONFIGURATION_MIN_ENTITIES: properties.Schema(
                    properties.Schema.NUMBER,
                    _('Minimum number of entities in this scaling group.'),
                    required=True
                ),
                GROUP_CONFIGURATION_METADATA: properties.Schema(
                    properties.Schema.MAP,
                    _('Arbitrary key/value metadata to associate with '
                      'this group.')
                ),
            },
            required=True
        ),
        LAUNCH_CONFIGURATION: properties.Schema(
            properties.Schema.MAP,
            _('Launch configuration.'),
            schema={
                LAUNCH_CONFIG_ARGS: properties.Schema(
                    properties.Schema.MAP,
                    _('Type-specific server launching arguments.'),
                    schema=_launch_configuration_args_schema,
                    required=True
                ),
                LAUNCH_CONFIG_TYPE: properties.Schema(
                    properties.Schema.STRING,
                    _('Launch configuration method. Only launch_server '
                      'is currently supported.'),
                    required=True,
                    constraints=[
                        constraints.AllowedValues(['launch_server']),
                    ]
                ),
            },
            required=True
        ),
        # We don't allow scaling policies to be specified here, despite the
        # fact that the API supports it. Users should use the ScalingPolicy
        # resource.
    }

    update_allowed_keys = ('Properties',)
    # Everything can be changed.
    update_allowed_properties = (GROUP_CONFIGURATION, LAUNCH_CONFIGURATION)

    def _get_group_config_args(self, groupconf):
        """Get the groupConfiguration-related pyrax arguments."""
        return dict(
            name=groupconf[self.GROUP_CONFIGURATION_NAME],
            cooldown=groupconf[self.GROUP_CONFIGURATION_COOLDOWN],
            min_entities=groupconf[self.GROUP_CONFIGURATION_MIN_ENTITIES],
            max_entities=groupconf[self.GROUP_CONFIGURATION_MAX_ENTITIES],
            metadata=groupconf.get(self.GROUP_CONFIGURATION_METADATA, None))

    def _get_launch_config_args(self, launchconf):
        """Get the launchConfiguration-related pyrax arguments."""
        lcargs = launchconf[self.LAUNCH_CONFIG_ARGS]
        server_args = lcargs[self.LAUNCH_CONFIG_ARGS_SERVER]
        lb_args = lcargs.get(self.LAUNCH_CONFIG_ARGS_LOAD_BALANCERS)
        lbs = copy.deepcopy(lb_args)
        if lbs:
            for lb in lbs:
                lbid = int(lb[self.LAUNCH_CONFIG_ARGS_LOAD_BALANCER_ID])
                lb[self.LAUNCH_CONFIG_ARGS_LOAD_BALANCER_ID] = lbid
        return dict(
            launch_config_type=launchconf[self.LAUNCH_CONFIG_TYPE],
            server_name=server_args[self.GROUP_CONFIGURATION_NAME],
            image=server_args[self.LAUNCH_CONFIG_ARGS_SERVER_IMAGE_REF],
            flavor=server_args[self.LAUNCH_CONFIG_ARGS_SERVER_FLAVOR_REF],
            disk_config=server_args.get(
                self.LAUNCH_CONFIG_ARGS_SERVER_DISK_CONFIG),
            metadata=server_args.get(self.GROUP_CONFIGURATION_METADATA),
            personality=server_args.get(
                self.LAUNCH_CONFIG_ARGS_SERVER_PERSONALITY),
            networks=server_args.get(self.LAUNCH_CONFIG_ARGS_SERVER_NETWORKS),
            load_balancers=lbs,
            key_name=server_args.get(self.LAUNCH_CONFIG_ARGS_SERVER_KEY_NAME),
        )

    def _get_create_args(self):
        """Get pyrax-style arguments for creating a scaling group."""
        args = self._get_group_config_args(
            self.properties[self.GROUP_CONFIGURATION])
        args['group_metadata'] = args.pop('metadata')
        args.update(self._get_launch_config_args(
            self.properties[self.LAUNCH_CONFIGURATION]))
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
        if self.GROUP_CONFIGURATION in prop_diff:
            args = self._get_group_config_args(
                prop_diff[self.GROUP_CONFIGURATION])
            asclient.replace(self.resource_id, **args)
        if self.LAUNCH_CONFIGURATION in prop_diff:
            args = self._get_launch_config_args(
                prop_diff[self.LAUNCH_CONFIGURATION])
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
            self.properties[self.GROUP_CONFIGURATION])
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

    PROPERTIES = (
        GROUP, NAME, CHANGE, CHANGE_PERCENT, DESIRED_CAPACITY,
        COOLDOWN, TYPE, ARGS,
    ) = (
        'group', 'name', 'change', 'changePercent', 'desiredCapacity',
        'cooldown', 'type', 'args',
    )

    properties_schema = {
        # group isn't in the post body, but it's in the URL to post to.
        GROUP: properties.Schema(
            properties.Schema.STRING,
            _('Scaling group ID that this policy belongs to.'),
            required=True
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of this scaling policy.'),
            required=True
        ),
        CHANGE: properties.Schema(
            properties.Schema.NUMBER,
            _('Amount to add to or remove from current number of instances. '
              'Incompatible with changePercent and desiredCapacity.')
        ),
        CHANGE_PERCENT: properties.Schema(
            properties.Schema.NUMBER,
            _('Percentage-based change to add or remove from current number '
              'of instances. Incompatible with change and desiredCapacity.')
        ),
        DESIRED_CAPACITY: properties.Schema(
            properties.Schema.NUMBER,
            _('Absolute number to set the number of instances to. '
              'Incompatible with change and changePercent.')
        ),
        COOLDOWN: properties.Schema(
            properties.Schema.NUMBER,
            _('Number of seconds after a policy execution during which '
              'further executions are disabled.')
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of this scaling policy. Specifies how the policy is '
              'executed.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['webhook', 'schedule',
                                           'cloud_monitoring']),
            ]
        ),
        ARGS: properties.Schema(
            properties.Schema.MAP,
            _('Type-specific arguments for the policy.')
        ),
    }

    update_allowed_keys = ('Properties',)
    # Everything other than group can be changed.
    update_allowed_properties = (
        NAME, CHANGE, CHANGE_PERCENT, DESIRED_CAPACITY, COOLDOWN, TYPE, ARGS,
    )

    def _get_args(self, properties):
        """Get pyrax-style create arguments for scaling policies."""
        args = dict(
            scaling_group=properties[self.GROUP],
            name=properties[self.NAME],
            policy_type=properties[self.TYPE],
            cooldown=properties[self.COOLDOWN],
        )
        if properties.get(self.CHANGE) is not None:
            args['change'] = properties[self.CHANGE]
        elif properties.get(self.CHANGE_PERCENT) is not None:
            args['change'] = properties[self.CHANGE_PERCENT]
            args['is_percent'] = True
        elif properties.get(self.DESIRED_CAPACITY) is not None:
            args['desired_capacity'] = properties[self.DESIRED_CAPACITY]
        if properties.get(self.ARGS) is not None:
            args['args'] = properties[self.ARGS]
        return args

    def handle_create(self):
        """
        Create the scaling policy, and initialize the resource ID to
        {group_id}:{policy_id}.
        """
        asclient = self.stack.clients.auto_scale()
        args = self._get_args(self.properties)
        policy = asclient.add_policy(**args)
        resource_id = '%s:%s' % (self.properties[self.GROUP], policy.id)
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
            asclient.delete_policy(self.properties[self.GROUP], policy_id)
        except NotFound:
            pass


class WebHook(resource.Resource):
    """
    Represents a Rackspace AutoScale webhook.

    Exposes the URLs of the webhook as attributes.
    """
    PROPERTIES = (
        POLICY, NAME, METADATA,
    ) = (
        'policy', 'name', 'metadata',
    )

    properties_schema = {
        POLICY: properties.Schema(
            properties.Schema.STRING,
            _('The policy that this webhook should apply to, in '
              '{group_id}:{policy_id} format. Generally a Ref to a Policy '
              'resource.'),
            required=True
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name of this webhook.'),
            required=True
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Arbitrary key/value metadata for this webhook.')
        ),
    }

    update_allowed_keys = ('Properties',)
    # Everything other than policy can be changed.
    update_allowed_properties = (NAME, METADATA)

    attributes_schema = {
        'executeUrl': _(
            "The url for executing the webhook (requires auth)."),
        'capabilityUrl': _(
            "The url for executing the webhook (doesn't require auth)."),
    }

    def _get_args(self, props):
        group_id, policy_id = props[self.POLICY].split(':', 1)
        return dict(
            name=props[self.NAME],
            scaling_group=group_id,
            policy=policy_id,
            metadata=props.get(self.METADATA))

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
        group_id, policy_id = self.properties[self.POLICY].split(':', 1)
        try:
            asclient.delete_webhook(group_id, policy_id, self.resource_id)
        except NotFound:
            pass


def resource_mapping():
    return {
        'Rackspace::AutoScale::Group': Group,
        'Rackspace::AutoScale::ScalingPolicy': ScalingPolicy,
        'Rackspace::AutoScale::WebHook': WebHook
    }


def available_resource_mapping():
    if PYRAX_INSTALLED:
        return resource_mapping()
    return {}
