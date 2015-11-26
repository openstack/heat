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

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class HostAggregate(resource.Resource):
    """A resource for further partition an availability zone with hosts.

    While availability zones are visible to users, host aggregates are only
    visible to administrators. Host aggregates started out as a way to use
    Xen hypervisor resource pools, but has been generalized to provide a
    mechanism to allow administrators to assign key-value pairs to groups of
    machines. Each node can have multiple aggregates, each aggregate can have
    multiple key-value pairs, and the same key-value pair can be assigned to
    multiple aggregate. This information can be used in the scheduler to
    enable advanced scheduling, to set up xen hypervisor resources pools or to
    define logical groups for migration.
    """

    support_status = support.SupportStatus(version='6.0.0')

    default_client_name = 'nova'

    entity = 'aggregates'

    required_service_extension = 'os-aggregates'

    PROPERTIES = (
        NAME, AVAILABILITY_ZONE, HOSTS, METADATA
    ) = (
        'name', 'availability_zone', 'hosts', 'metadata'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the aggregate.'),
            required=True,
            update_allowed=True,
        ),
        AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _('Name for the availability zone.'),
            required=True,
            update_allowed=True,
        ),
        HOSTS: properties.Schema(
            properties.Schema.LIST,
            _('List of hosts to join aggregate.'),
            update_allowed=True,
            schema=properties.Schema(
                properties.Schema.STRING,
                constraints=[constraints.CustomConstraint('nova.host')],
            ),
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Arbitrary key/value metadata to store information '
              'for aggregate.'),
            update_allowed=True,
            default={}
        ),

    }

    def _find_diff(self, update_prps, stored_prps):
        add_prps = list(set(update_prps or []) - set(stored_prps or []))
        remove_prps = list(set(stored_prps or []) - set(update_prps or []))
        return add_prps, remove_prps

    def handle_create(self):
        name = self.properties[self.NAME]
        availability_zone = self.properties[self.AVAILABILITY_ZONE]
        hosts = self.properties[self.HOSTS] or []
        metadata = self.properties[self.METADATA] or {}

        aggregate = self.client().aggregates.create(
            name=name, availability_zone=availability_zone
        )
        self.resource_id_set(aggregate.id)
        if metadata:
            aggregate.set_metadata(metadata)
        for host in hosts:
            aggregate.add_host(host)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            aggregate = self.client().aggregates.get(self.resource_id)
            if self.HOSTS in prop_diff:
                new_hosts = prop_diff.pop(self.HOSTS)
                old_hosts = aggregate.hosts
                add_hosts, remove_hosts = self._find_diff(new_hosts, old_hosts)
                for host in add_hosts:
                    aggregate.add_host(host)
                for host in remove_hosts:
                    aggregate.remove_host(host)
            if self.METADATA in prop_diff:
                metadata = prop_diff.pop(self.METADATA)
                if metadata:
                    aggregate.set_metadata(metadata)

            if prop_diff:
                aggregate.update(prop_diff)

    def handle_delete(self):
        if self.resource_id is None:
            return

        with self.client_plugin().ignore_not_found:
            aggregate = self.client().aggregates.get(self.resource_id)
            for host in aggregate.hosts:
                aggregate.remove_host(host)
        super(HostAggregate, self).handle_delete()

    def parse_live_resource_data(self, resource_properties, resource_data):
        aggregate_reality = {}

        for key in self.PROPERTIES:
            aggregate_reality.update({key: resource_data.get(key)})

        return aggregate_reality


def resource_mapping():
    return {
        'OS::Nova::HostAggregate': HostAggregate
    }
