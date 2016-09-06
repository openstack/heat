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
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


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


def resource_mapping():
    return {
        'OS::Cinder::QoSSpecs': QoSSpecs,
    }
