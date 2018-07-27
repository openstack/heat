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

import copy

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class Container(resource.Resource):
    """A resource that creates a Zun Container.

    This resource creates a Zun container.
    """

    support_status = support.SupportStatus(version='9.0.0')

    PROPERTIES = (
        NAME, IMAGE, COMMAND, CPU, MEMORY,
        ENVIRONMENT, WORKDIR, LABELS, IMAGE_PULL_POLICY,
        RESTART_POLICY, INTERACTIVE, IMAGE_DRIVER, HINTS,
        HOSTNAME, SECURITY_GROUPS, MOUNTS,
    ) = (
        'name', 'image', 'command', 'cpu', 'memory',
        'environment', 'workdir', 'labels', 'image_pull_policy',
        'restart_policy', 'interactive', 'image_driver', 'hints',
        'hostname', 'security_groups', 'mounts',
    )

    _MOUNT_KEYS = (
        VOLUME_ID, MOUNT_PATH, VOLUME_SIZE
    ) = (
        'volume_id', 'mount_path', 'volume_size',
    )

    ATTRIBUTES = (
        NAME, ADDRESSES
    ) = (
        'name', 'addresses'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the container.'),
            update_allowed=True
        ),
        IMAGE: properties.Schema(
            properties.Schema.STRING,
            _('Name or ID of the image.'),
            required=True
        ),
        COMMAND: properties.Schema(
            properties.Schema.STRING,
            _('Send command to the container.'),
        ),
        CPU: properties.Schema(
            properties.Schema.NUMBER,
            _('The number of virtual cpus.'),
            update_allowed=True
        ),
        MEMORY: properties.Schema(
            properties.Schema.INTEGER,
            _('The container memory size in MiB.'),
            update_allowed=True
        ),
        ENVIRONMENT: properties.Schema(
            properties.Schema.MAP,
            _('The environment variables.'),
        ),
        WORKDIR: properties.Schema(
            properties.Schema.STRING,
            _('The working directory for commands to run in.'),
        ),
        LABELS: properties.Schema(
            properties.Schema.MAP,
            _('Adds a map of labels to a container. '
              'May be used multiple times.'),
        ),
        IMAGE_PULL_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('The policy which determines if the image should '
              'be pulled prior to starting the container.'),
            constraints=[
                constraints.AllowedValues(['ifnotpresent', 'always',
                                           'never']),
            ]
        ),
        RESTART_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('Restart policy to apply when a container exits. Possible '
              'values are "no", "on-failure[:max-retry]", "always", and '
              '"unless-stopped".'),
        ),
        INTERACTIVE: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Keep STDIN open even if not attached.'),
        ),
        IMAGE_DRIVER: properties.Schema(
            properties.Schema.STRING,
            _('The image driver to use to pull container image.'),
            constraints=[
                constraints.AllowedValues(['docker', 'glance']),
            ]
        ),
        HINTS: properties.Schema(
            properties.Schema.MAP,
            _('Arbitrary key-value pairs for scheduler to select host.'),
            support_status=support.SupportStatus(version='10.0.0'),
        ),
        HOSTNAME: properties.Schema(
            properties.Schema.STRING,
            _('The hostname of the container.'),
            support_status=support.SupportStatus(version='10.0.0'),
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('List of security group names or IDs.'),
            support_status=support.SupportStatus(version='10.0.0'),
            default=[]
        ),
        MOUNTS: properties.Schema(
            properties.Schema.LIST,
            _('A list of volumes mounted inside the container.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    VOLUME_ID: properties.Schema(
                        properties.Schema.STRING,
                        _('The ID or name of the cinder volume mount to '
                          'the container.'),
                        constraints=[
                            constraints.CustomConstraint('cinder.volume')
                        ]
                    ),
                    VOLUME_SIZE: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The size of the cinder volume to create.'),
                    ),
                    MOUNT_PATH: properties.Schema(
                        properties.Schema.STRING,
                        _('The filesystem path inside the container.'),
                        required=True,
                    ),
                },
            )
        ),
    }

    attributes_schema = {
        NAME: attributes.Schema(
            _('Name of the container.'),
            type=attributes.Schema.STRING
        ),
        ADDRESSES: attributes.Schema(
            _('A dict of all network addresses with corresponding port_id. '
              'Each network will have two keys in dict, they are network '
              'name and network id. '
              'The port ID may be obtained through the following expression: '
              '"{get_attr: [<container>, addresses, <network name_or_id>, 0, '
              'port]}".'),
            type=attributes.Schema.MAP
        ),
    }

    default_client_name = 'zun'

    entity = 'containers'

    def validate(self):
        super(Container, self).validate()

        policy = self.properties[self.RESTART_POLICY]
        if policy and not self._parse_restart_policy(policy):
            msg = _('restart_policy "%s" is invalid. Valid values are '
                    '"no", "on-failure[:max-retry]", "always", and '
                    '"unless-stopped".') % policy
            raise exception.StackValidationFailed(message=msg)

        mounts = self.properties[self.MOUNTS] or []
        for mount in mounts:
            self._validate_mount(mount)

    def _validate_mount(self, mount):
        volume_id = mount.get(self.VOLUME_ID)
        volume_size = mount.get(self.VOLUME_SIZE)

        if volume_id is None and volume_size is None:
            msg = _('One of the properties "%(id)s" or "%(size)s" '
                    'should be set for the specified mount of '
                    'container "%(container)s".'
                    '') % dict(id=self.VOLUME_ID,
                               size=self.VOLUME_SIZE,
                               container=self.name)
            raise exception.StackValidationFailed(message=msg)

        # Don't allow specify volume_id and volume_size at the same time
        if volume_id and volume_size:
            raise exception.ResourcePropertyConflict(
                "/".join([self.NETWORKS, self.VOLUME_ID]),
                "/".join([self.NETWORKS, self.VOLUME_SIZE]))

    def handle_create(self):
        args = dict((k, v) for k, v in self.properties.items()
                    if v is not None)
        policy = args.pop(self.RESTART_POLICY, None)
        if policy:
            args[self.RESTART_POLICY] = self._parse_restart_policy(policy)
        mounts = args.pop(self.MOUNTS, None)
        if mounts:
            args[self.MOUNTS] = self._build_mounts(mounts)
        container = self.client().containers.run(**args)
        self.resource_id_set(container.uuid)
        return container.uuid

    def _parse_restart_policy(self, policy):
        restart_policy = None
        if ":" in policy:
            policy, count = policy.split(":")
            if policy in ['on-failure']:
                restart_policy = {"Name": policy,
                                  "MaximumRetryCount": count or '0'}
        else:
            if policy in ['always', 'unless-stopped', 'on-failure', 'no']:
                restart_policy = {"Name": policy, "MaximumRetryCount": '0'}

        return restart_policy

    def _build_mounts(self, mounts):
        mnts = []
        for mount in mounts:
            mnt_info = {'destination': mount[self.MOUNT_PATH]}
            if mount.get(self.VOLUME_ID):
                mnt_info['source'] = mount[self.VOLUME_ID]
            if mount.get(self.VOLUME_SIZE):
                mnt_info['size'] = mount[self.VOLUME_SIZE]
            mnts.append(mnt_info)
        return mnts

    def check_create_complete(self, id):
        container = self.client().containers.get(id)
        if container.status in ('Creating', 'Created'):
            return False
        elif container.status == 'Running':
            return True
        elif container.status == 'Stopped':
            if container.interactive:
                msg = (_("Error in creating container '%(name)s' - "
                         "interactive mode was enabled but the container "
                         "has stopped running") % {'name': self.name})
                raise exception.ResourceInError(
                    status_reason=msg, resource_status=container.status)
            return True
        elif container.status == 'Error':
            msg = (_("Error in creating container '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': container.status_reason})
            raise exception.ResourceInError(status_reason=msg,
                                            resource_status=container.status)
        else:
            msg = (_("Unknown status Container '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': container.status_reason})
            raise exception.ResourceUnknownStatus(status_reason=msg,
                                                  resource_status=container
                                                  .status)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self.client_plugin().update_container(self.resource_id, **prop_diff)

    def handle_delete(self):
        if not self.resource_id:
            return
        try:
            self.client().containers.delete(self.resource_id, stop=True)
            return self.resource_id
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)

    def check_delete_complete(self, id):
        if not id:
            return True
        try:
            self.client().containers.get(id)
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)
            return True
        return False

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        try:
            container = self.client().containers.get(self.resource_id)
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)
            return ''

        if name == self.ADDRESSES:
            return self._extend_addresses(container)

        return getattr(container, name, '')

    def _extend_addresses(self, container):
        """Method adds network name to list of addresses.

        This method is used only for resolving attributes.
        """
        nets = self.neutron().list_networks()['networks']
        id_name_mapping_on_network = {net['id']: net['name']
                                      for net in nets}
        addresses = copy.deepcopy(container.addresses)
        for net_uuid in container.addresses or {}:
            addr_list = addresses[net_uuid]
            net_name = id_name_mapping_on_network.get(net_uuid)
            if not net_name:
                continue

            addresses.setdefault(net_name, [])
            addresses[net_name] += addr_list

        return addresses


def resource_mapping():
    return {
        'OS::Zun::Container': Container
    }
