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

from heat.engine import clients
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.neutron import neutron

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException


class MeteringLabel(neutron.NeutronResource):
    """
    A resource for creating neutron metering label.
    """

    PROPERTIES = (
        NAME, DESCRIPTION,
    ) = (
        'name', 'description',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the metering label.')
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the metering label.'),
        )
    }

    attributes_schema = {
        'name': _('Name of the metering label.'),
        'description': _('Description of the metering label.'),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        metering_label = self.neutron().create_metering_label(
            {'metering_label': props})['metering_label']

        self.resource_id_set(metering_label['id'])

    def _show_resource(self):
        return self.neutron().show_metering_label(
            self.resource_id)['metering_label']

    def handle_delete(self):
        try:
            self.neutron().delete_metering_label(self.resource_id)
        except NeutronClientException as ex:
            self._handle_not_found_exception(ex)
        else:
            return self._delete_task()


class MeteringRule(neutron.NeutronResource):
    """
    A resource to create rule for some label.
    """

    PROPERTIES = (
        METERING_LABEL_ID, REMOTE_IP_PREFIX, DIRECTION, EXCLUDED,
    ) = (
        'metering_label_id', 'remote_ip_prefix', 'direction', 'excluded',
    )

    properties_schema = {
        METERING_LABEL_ID: properties.Schema(
            properties.Schema.STRING,
            _('The metering label ID to associate with this metering rule.'),
            required=True
        ),
        REMOTE_IP_PREFIX: properties.Schema(
            properties.Schema.STRING,
            _('Indicates remote IP prefix to be associated with this '
              'metering rule.'),
            required=True,
        ),
        DIRECTION: properties.Schema(
            properties.Schema.STRING,
            _('The direction in which metering rule is applied, '
              'either ingress or egress.'),
            default='ingress',
            constraints=[constraints.AllowedValues((
                'ingress', 'egress'))]
        ),
        EXCLUDED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Specify whether the remote_ip_prefix will be excluded or '
              'not from traffic counters of the metering label. For example '
              'to not count the traffic of a specific IP address of a range.'),
            default='False'
        )
    }

    attributes_schema = {
        'direction': _('The direction in which metering rule is applied.'),
        'excluded': _('Exclude state for cidr.'),
        'metering_label_id': _('The metering label ID to associate with '
                               'this metering rule..'),
        'remote_ip_prefix': _('CIDR to be associated with this metering '
                              'rule.'),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        metering_label_rule = self.neutron().create_metering_label_rule(
            {'metering_label_rule': props})['metering_label_rule']

        self.resource_id_set(metering_label_rule['id'])

    def _show_resource(self):
        return self.neutron().show_metering_label_rule(
            self.resource_id)['metering_label_rule']

    def handle_delete(self):
        try:
            self.neutron().delete_metering_label_rule(self.resource_id)
        except NeutronClientException as ex:
            self._handle_not_found_exception(ex)
        else:
            return self._delete_task()


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::MeteringLabel': MeteringLabel,
        'OS::Neutron::MeteringRule': MeteringRule,
    }
