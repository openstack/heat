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
import six

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class DesignateDomain(resource.Resource):
    """Heat Template Resource for Designate Domain.

    Designate provides DNS-as-a-Service services for OpenStack. So, domain
    is a realm with an identification string, unique in DNS.
    """

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='10.0.0',
        message=_('Use OS::Designate::Zone instead.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            version='8.0.0',
            previous_status=support.SupportStatus(version='5.0.0')))

    entity = 'domains'

    default_client_name = 'designate'

    PROPERTIES = (
        NAME, TTL, DESCRIPTION, EMAIL
    ) = (
        'name', 'ttl', 'description', 'email'
    )

    ATTRIBUTES = (
        SERIAL,
    ) = (
        'serial',
    )

    properties_schema = {
        # Based on RFC 1035, length of name is set to max of 255
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Domain name.'),
            required=True,
            constraints=[constraints.Length(max=255)]
        ),
        # Based on RFC 1035, range for ttl is set to 1 to signed 32 bit number
        TTL: properties.Schema(
            properties.Schema.INTEGER,
            _('Time To Live (Seconds).'),
            update_allowed=True,
            constraints=[constraints.Range(min=1,
                                           max=2147483647)]
        ),
        # designate mandates to the max length of 160 for description
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of domain.'),
            update_allowed=True,
            constraints=[constraints.Length(max=160)]
        ),
        EMAIL: properties.Schema(
            properties.Schema.STRING,
            _('Domain email.'),
            update_allowed=True,
            required=True
        )
    }

    attributes_schema = {
        SERIAL: attributes.Schema(
            _("DNS domain serial."),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        args = dict((k, v) for k, v in six.iteritems(self.properties) if v)
        domain = self.client_plugin().domain_create(**args)

        self.resource_id_set(domain.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        args = dict()

        if prop_diff.get(self.EMAIL):
            args['email'] = prop_diff.get(self.EMAIL)

        if prop_diff.get(self.TTL):
            args['ttl'] = prop_diff.get(self.TTL)

        if prop_diff.get(self.DESCRIPTION):
            args['description'] = prop_diff.get(self.DESCRIPTION)

        if len(args.keys()) > 0:
            args['id'] = self.resource_id
            self.client_plugin().domain_update(**args)

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        if name == self.SERIAL:
            domain = self.client().domains.get(self.resource_id)
            return domain.serial

    # FIXME(kanagaraj-manickam) Remove this method once designate defect
    # 1485552 is fixed.
    def _show_resource(self):
        return dict(self.client().domains.get(self.resource_id).items())

    def parse_live_resource_data(self, resource_properties, resource_data):
        domain_reality = {}

        for key in self.PROPERTIES:
            domain_reality.update({key: resource_data.get(key)})

        return domain_reality


def resource_mapping():
    return {
        'OS::Designate::Domain': DesignateDomain
    }
