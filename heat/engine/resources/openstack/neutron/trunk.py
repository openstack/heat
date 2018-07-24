# Copyright 2017 Ericsson
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

from oslo_log import log as logging

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation

LOG = logging.getLogger(__name__)


class Trunk(neutron.NeutronResource):
    """A resource for managing Neutron trunks.

    Requires Neutron Trunk Extension to be enabled::

      $ openstack extension show trunk

    The network trunk service allows multiple networks to be connected to
    an instance using a single virtual NIC (vNIC). Multiple networks can
    be presented to an instance by connecting the instance to a single port.

    Users can create a port, associate it with a trunk (as the trunk's parent)
    and launch an instance on that port. Users can dynamically attach and
    detach additional networks without disrupting operation of the instance.

    Every trunk has a parent port and can have any number (0, 1, ...) of
    subports. The parent port is the port that the instance is directly
    associated with and its traffic is always untagged inside the instance.
    Users must specify the parent port of the trunk when launching an
    instance attached to a trunk.

    A network presented by a subport is the network of the associated port.
    When creating a subport, a ``segmentation_type`` and ``segmentation_id``
    may be required by the driver so the user can distinguish the networks
    inside the instance. As of release Pike only ``segmentation_type``
    ``vlan`` is supported. ``segmentation_id`` defines the segmentation ID
    on which the subport network is presented to the instance.

    Note that some Neutron backends (primarily Open vSwitch) only allow
    trunk creation before an instance is booted on the parent port. To avoid
    a possible race condition when booting an instance with a trunk it is
    strongly recommended to refer to the trunk's parent port indirectly in
    the template via ``get_attr``. For example::

      trunk:
        type: OS::Neutron::Trunk
        properties:
          port: ...
      instance:
        type: OS::Nova::Server
        properties:
          networks:
            - { port: { get_attr: [trunk, port_id] } }

    Though other Neutron backends may tolerate the direct port reference
    (and the possible reverse ordering of API requests implied) it's a good
    idea to avoid writing Neutron backend specific templates.
    """

    entity = 'trunk'

    required_service_extension = 'trunk'

    support_status = support.SupportStatus(
        status=support.SUPPORTED,
        version='9.0.0',
    )

    PROPERTIES = (
        NAME, PARENT_PORT, SUB_PORTS, DESCRIPTION, ADMIN_STATE_UP,
    ) = (
        'name', 'port', 'sub_ports', 'description', 'admin_state_up',
    )

    _SUBPORT_KEYS = (
        PORT, SEGMENTATION_TYPE, SEGMENTATION_ID,
    ) = (
        'port', 'segmentation_type', 'segmentation_id',
    )

    _subport_schema = {
        PORT: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of a port to be used as a subport.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.port'),
            ],
        ),
        SEGMENTATION_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Segmentation type to be used on the subport.'),
            required=True,
            # TODO(nilles): custom constraint 'neutron.trunk_segmentation_type'
            constraints=[
                constraints.AllowedValues(['vlan']),
            ],
        ),
        SEGMENTATION_ID: properties.Schema(
            properties.Schema.INTEGER,
            _('The segmentation ID on which the subport network is presented '
              'to the instance.'),
            required=True,
            # TODO(nilles): custom constraint 'neutron.trunk_segmentation_id'
            constraints=[
                constraints.Range(1, 4094),
            ],
        ),
    }

    ATTRIBUTES = (
        PORT_ATTR,
    ) = (
        'port_id',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('A string specifying a symbolic name for the trunk, which is '
              'not required to be uniqe.'),
            update_allowed=True,
        ),
        PARENT_PORT: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of a port to be used as a parent port.'),
            required=True,
            immutable=True,
            constraints=[
                constraints.CustomConstraint('neutron.port'),
            ],
        ),
        SUB_PORTS: properties.Schema(
            properties.Schema.LIST,
            _('List with 0 or more map elements containing subport details.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema=_subport_schema,
            ),
            update_allowed=True,
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the trunk.'),
            update_allowed=True,
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Enable/disable subport addition, removal and trunk delete.'),
            update_allowed=True,
        ),
    }

    attributes_schema = {
        PORT_ATTR: attributes.Schema(
            _('ID or name of a port used as a parent port.'),
            type=attributes.Schema.STRING,
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.PARENT_PORT],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_PORT
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.SUB_PORTS, self.PORT],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_PORT
            ),
        ]

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        props['port_id'] = props.pop(self.PARENT_PORT)

        if self.SUB_PORTS in props and props[self.SUB_PORTS]:
            for sub_port in props[self.SUB_PORTS]:
                sub_port['port_id'] = sub_port.pop(self.PORT)

        LOG.debug('attempt to create trunk: %s', props)
        trunk = self.client().create_trunk({'trunk': props})['trunk']
        self.resource_id_set(trunk['id'])

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                LOG.debug('attempt to delete trunk: %s', self.resource_id)
                self.client().delete_trunk(self.resource_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Handle update to a trunk in (at most) three neutron calls.

        Call #1) Update all changed properties but 'sub_ports'.
            PUT /v2.0/trunks/TRUNK_ID
            openstack network trunk set

        Call #2) Delete subports not needed anymore.
            PUT /v2.0/trunks/TRUNK_ID/remove_subports
            openstack network trunk unset --subport

        Call #3) Create new subports.
            PUT /v2.0/trunks/TRUNK_ID/add_subports
            openstack network trunk set --subport

        A single neutron port cannot be two subports at the same time (ie.
        have two segmentation (type, ID)s on the same trunk or to belong to
        two trunks). Therefore we have to delete old subports before creating
        new ones to avoid conflicts.
        """

        LOG.debug('attempt to update trunk %s', self.resource_id)

        # NOTE(bence romsics): We want to do set operations on the subports,
        # however we receive subports represented as dicts. In Python
        # mutable objects like dicts are not hashable so they cannot be
        # inserted into sets. So we convert subport dicts to (immutable)
        # frozensets in order to do the set operations.
        def dict2frozenset(d):
            """Convert a dict to a frozenset.

            Create an immutable equivalent of a dict, so it's hashable
            therefore can be used as an element of a set or a key of another
            dictionary.
            """
            return frozenset(d.items())

        # NOTE(bence romsics): prop_diff contains a shallow diff of the
        # properties, so if we had used that to update subports we would
        # re-create all subports even if just a single subport changed. So we
        # need to forget about prop_diff['sub_ports'] and diff out the real
        # subport changes from self.properties and json_snippet.
        if 'sub_ports' in prop_diff:
            del prop_diff['sub_ports']

        sub_ports_prop_old = self.properties[self.SUB_PORTS] or []
        sub_ports_prop_new = json_snippet.properties(
            self.properties_schema)[self.SUB_PORTS] or []

        subports_old = {dict2frozenset(d): d for d in sub_ports_prop_old}
        subports_new = {dict2frozenset(d): d for d in sub_ports_prop_new}

        old_set = set(subports_old.keys())
        new_set = set(subports_new.keys())

        delete = old_set - new_set
        create = new_set - old_set

        dicts_delete = [subports_old[fs] for fs in delete]
        dicts_create = [subports_new[fs] for fs in create]

        LOG.debug('attempt to delete subports of trunk %s: %s',
                  self.resource_id, dicts_delete)
        LOG.debug('attempt to create subports of trunk %s: %s',
                  self.resource_id, dicts_create)

        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client().update_trunk(self.resource_id, {'trunk': prop_diff})

        if dicts_delete:
            delete_body = self.prepare_trunk_remove_subports_body(dicts_delete)
            self.client().trunk_remove_subports(self.resource_id, delete_body)

        if dicts_create:
            create_body = self.prepare_trunk_add_subports_body(dicts_create)
            self.client().trunk_add_subports(self.resource_id, create_body)

    def check_update_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    @staticmethod
    def prepare_trunk_remove_subports_body(subports):
        """Prepares body for PUT /v2.0/trunks/TRUNK_ID/remove_subports."""

        return {
            'sub_ports': [
                {'port_id': sp['port']} for sp in subports
            ]
        }

    @staticmethod
    def prepare_trunk_add_subports_body(subports):
        """Prepares body for PUT /v2.0/trunks/TRUNK_ID/add_subports."""

        return {
            'sub_ports': [
                {'port_id': sp['port'],
                 'segmentation_type': sp['segmentation_type'],
                 'segmentation_id': sp['segmentation_id']}
                for sp in subports
            ]
        }


def resource_mapping():
    return {
        'OS::Neutron::Trunk': Trunk,
    }
