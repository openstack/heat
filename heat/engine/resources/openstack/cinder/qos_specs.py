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
from heat.engine import translation


class QoSSpecs(resource.Resource):
    """A resource for creating cinder QoS specs.

    Users can ask for a specific volume type. Part of that volume type is a
    string that defines the QoS of the volume IO (fast, normal, or slow).
    Backends that can handle all of the demands of the volume type become
    candidates for scheduling. Usage of this resource restricted to admins
    only by default policy.
    """

    support_status = support.SupportStatus(version='7.0.0')

    default_client_name = 'cinder'
    entity = 'qos_specs'
    required_service_extension = 'qos-specs'

    PROPERTIES = (
        NAME, SPECS,
    ) = (
        'name', 'specs',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the QoS.'),
        ),
        SPECS: properties.Schema(
            properties.Schema.MAP,
            _('The specs key and value pairs of the QoS.'),
            required=True,
            update_allowed=True
        ),
    }

    def _find_diff(self, update_prps, stored_prps):
        remove_prps = list(
            set(stored_prps.keys() or []) - set(update_prps.keys() or [])
        )
        add_prps = dict(set(update_prps.items() or []) - set(
            stored_prps.items() or []))
        return add_prps, remove_prps

    def handle_create(self):
        name = (self.properties[self.NAME] or
                self.physical_resource_name())
        specs = self.properties[self.SPECS]

        qos = self.client().qos_specs.create(name, specs)
        self.resource_id_set(qos.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Update the specs for QoS."""

        new_specs = prop_diff.get(self.SPECS)
        old_specs = self.properties[self.SPECS]
        add_specs, remove_specs = self._find_diff(new_specs, old_specs)
        if self.resource_id is not None:
            # Set new specs to QoS Specs
            if add_specs:
                self.client().qos_specs.set_keys(self.resource_id, add_specs)
            # Unset old specs from QoS Specs
            if remove_specs:
                self.client().qos_specs.unset_keys(self.resource_id,
                                                   remove_specs)

    def handle_delete(self):
        if self.resource_id is not None:
            self.client().qos_specs.disassociate_all(self.resource_id)
        super(QoSSpecs, self).handle_delete()


class QoSAssociation(resource.Resource):
    """A resource to associate cinder QoS specs with volume types.

    Usage of this resource restricted to admins only by default policy.
    """

    support_status = support.SupportStatus(version='8.0.0')

    default_client_name = 'cinder'

    required_service_extension = 'qos-specs'

    PROPERTIES = (
        QOS_SPECS, VOLUME_TYPES,
    ) = (
        'qos_specs', 'volume_types',
    )

    properties_schema = {
        QOS_SPECS: properties.Schema(
            properties.Schema.STRING,
            _('ID or Name of the QoS specs.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('cinder.qos_specs')
            ],
        ),
        VOLUME_TYPES: properties.Schema(
            properties.Schema.LIST,
            _('List of volume type IDs or Names to be attached to QoS specs.'),
            schema=properties.Schema(
                properties.Schema.STRING,
                _('A volume type to attach specs.'),
                constraints=[
                    constraints.CustomConstraint('cinder.vtype')
                ],
            ),
            update_allowed=True,
            required=True,

        ),
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.VOLUME_TYPES],
                client_plugin=self.client_plugin(),
                finder='get_volume_type'
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.QOS_SPECS],
                client_plugin=self.client_plugin(),
                finder='get_qos_specs'
            )
        ]

    def _find_diff(self, update_prps, stored_prps):
        add_prps = list(set(update_prps or []) - set(stored_prps or []))
        remove_prps = list(set(stored_prps or []) - set(update_prps or []))
        return add_prps, remove_prps

    def handle_create(self):
        for vt in self.properties[self.VOLUME_TYPES]:
            self.client().qos_specs.associate(self.properties[self.QOS_SPECS],
                                              vt)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Associate volume types to QoS."""

        qos_specs = self.properties[self.QOS_SPECS]
        new_associate_vts = prop_diff.get(self.VOLUME_TYPES)
        old_associate_vts = self.properties[self.VOLUME_TYPES]
        add_associate_vts, remove_associate_vts = self._find_diff(
            new_associate_vts, old_associate_vts)
        for vt in add_associate_vts:
            self.client().qos_specs.associate(qos_specs, vt)
        for vt in remove_associate_vts:
            self.client().qos_specs.disassociate(qos_specs, vt)

    def handle_delete(self):
        volume_types = self.properties[self.VOLUME_TYPES]
        for vt in volume_types:
            self.client().qos_specs.disassociate(
                self.properties[self.QOS_SPECS], vt)


def resource_mapping():
    return {
        'OS::Cinder::QoSSpecs': QoSSpecs,
        'OS::Cinder::QoSAssociation': QoSAssociation,
    }
