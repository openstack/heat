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
        RESTART_POLICY, INTERACTIVE, IMAGE_DRIVER
    ) = (
        'name', 'image', 'command', 'cpu', 'memory',
        'environment', 'workdir', 'labels', 'image_pull_policy',
        'restart_policy', 'interactive', 'image_driver'
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

    def handle_create(self):
        args = dict((k, v) for k, v in self.properties.items()
                    if v is not None)
        policy = args.pop(self.RESTART_POLICY, None)
        if policy:
            args[self.RESTART_POLICY] = self._parse_restart_policy(policy)
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
        if self.NAME in prop_diff:
            name = prop_diff.pop(self.NAME)
            self.client().containers.rename(self.resource_id, name=name)
        if prop_diff:
            self.client().containers.update(self.resource_id, **prop_diff)

    def handle_delete(self):
        if not self.resource_id:
            return
        try:
            self.client().containers.delete(self.resource_id, force=True)
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        try:
            container = self.client().containers.get(self.resource_id)
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)
            return ''
        return getattr(container, name, '')


def resource_mapping():
    return {
        'OS::Zun::Container': Container
    }
