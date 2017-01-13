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
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support


class MeteringLabel(neutron.NeutronResource):
    """A resource for creating neutron metering label.

    The idea is to meter this at the L3 routers levels. The point is to allow
    operators to configure IP ranges and to assign a label to them. For example
    we will be able to set two labels; one for the internal traffic, and the
    other one for the external traffic. Each label will measure the traffic for
    a specific set of IP range. Then, bandwidth measurement will be sent for
    each label to the Oslo notification system and could be collected by
    Ceilometer.
    """

    support_status = support.SupportStatus(version='2014.1')

    entity = 'metering_label'

    PROPERTIES = (
        NAME, DESCRIPTION, SHARED,
    ) = (
        'name', 'description', 'shared',
    )

    ATTRIBUTES = (
        NAME_ATTR, DESCRIPTION_ATTR, SHARED_ATTR,
    ) = (
        'name', 'description', 'shared',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the metering label.')
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the metering label.'),
        ),
        SHARED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether the metering label should be shared '
              'across all tenants.'),
            default=False,
            support_status=support.SupportStatus(version='2015.1'),
        ),
    }

    attributes_schema = {
        NAME_ATTR: attributes.Schema(
            _('Name of the metering label.'),
            type=attributes.Schema.STRING
        ),
        DESCRIPTION_ATTR: attributes.Schema(
            _('Description of the metering label.'),
            type=attributes.Schema.STRING
        ),
        SHARED_ATTR: attributes.Schema(
            _('Shared status of the metering label.'),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        metering_label = self.client().create_metering_label(
            {'metering_label': props})['metering_label']

        self.resource_id_set(metering_label['id'])

    def handle_delete(self):
        try:
            self.client().delete_metering_label(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True


class MeteringRule(neutron.NeutronResource):
    """A resource to create rule for some label.

    Resource for allowing specified label to measure the traffic for a specific
    set of ip range.
    """

    support_status = support.SupportStatus(version='2014.1')

    entity = 'metering_label_rule'

    PROPERTIES = (
        METERING_LABEL_ID, REMOTE_IP_PREFIX, DIRECTION, EXCLUDED,
    ) = (
        'metering_label_id', 'remote_ip_prefix', 'direction', 'excluded',
    )

    ATTRIBUTES = (
        DIRECTION_ATTR, EXCLUDED_ATTR, METERING_LABEL_ID_ATTR,
        REMOTE_IP_PREFIX_ATTR,
    ) = (
        'direction', 'excluded', 'metering_label_id',
        'remote_ip_prefix',
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
        DIRECTION_ATTR: attributes.Schema(
            _('The direction in which metering rule is applied.'),
            type=attributes.Schema.STRING
        ),
        EXCLUDED_ATTR: attributes.Schema(
            _('Exclude state for cidr.'),
            type=attributes.Schema.STRING
        ),
        METERING_LABEL_ID_ATTR: attributes.Schema(
            _('The metering label ID to associate with this metering rule.'),
            type=attributes.Schema.STRING
        ),
        REMOTE_IP_PREFIX_ATTR: attributes.Schema(
            _('CIDR to be associated with this metering rule.'),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        metering_label_rule = self.client().create_metering_label_rule(
            {'metering_label_rule': props})['metering_label_rule']

        self.resource_id_set(metering_label_rule['id'])

    def handle_delete(self):
        try:
            self.client().delete_metering_label_rule(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True


def resource_mapping():
    return {
        'OS::Neutron::MeteringLabel': MeteringLabel,
        'OS::Neutron::MeteringRule': MeteringRule,
    }
