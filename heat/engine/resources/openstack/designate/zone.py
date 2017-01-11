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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class DesignateZone(resource.Resource):
    """Heat Template Resource for Designate Zone.

    Designate provides DNS-as-a-Service services for OpenStack. So, zone, part
    of domain is a realm with an identification string, unique in DNS.
    """

    support_status = support.SupportStatus(
        version='8.0.0')

    PROPERTIES = (
        NAME, TTL, DESCRIPTION, EMAIL, TYPE, MASTERS
    ) = (
        'name', 'ttl', 'description', 'email', 'type', 'masters'
    )

    ATTRIBUTES = (
        SERIAL,
    ) = (
        'serial',
    )

    TYPES = (
        PRIMARY, SECONDARY
    ) = (
        'PRIMARY', 'SECONDARY'
    )

    properties_schema = {
        # Based on RFC 1035, length of name is set to max of 255
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('DNS Name for the zone.'),
            required=True,
            constraints=[constraints.Length(max=255)]
        ),
        # Based on RFC 1035, range for ttl is set to 1 to signed 32 bit number
        TTL: properties.Schema(
            properties.Schema.INTEGER,
            _('Time To Live (Seconds) for the zone.'),
            update_allowed=True,
            constraints=[constraints.Range(min=1,
                                           max=2147483647)]
        ),
        # designate mandates to the max length of 160 for description
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of zone.'),
            update_allowed=True,
            constraints=[constraints.Length(max=160)]
        ),
        EMAIL: properties.Schema(
            properties.Schema.STRING,
            _('E-mail for the zone. Used in SOA records for the zone. '
              'It is required for PRIMARY Type, otherwise ignored.'),
            update_allowed=True,
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of zone. PRIMARY is controlled by Designate, SECONDARY '
              'zones are slaved from another DNS Server.'),
            default=PRIMARY,
            constraints=[constraints.AllowedValues(
                allowed=TYPES)]
        ),
        MASTERS: properties.Schema(
            properties.Schema.LIST,
            _('The servers to slave from to get DNS information and is '
              'mandatory for zone type SECONDARY, otherwise ignored.'),
            update_allowed=True
        )
    }

    attributes_schema = {
        SERIAL: attributes.Schema(
            _("DNS zone serial number."),
            type=attributes.Schema.STRING
        ),
    }

    default_client_name = 'designate'

    entity = 'zones'

    def client(self):
        return super(DesignateZone,
                     self).client(version=self.client_plugin().V2)

    def validate(self):
        super(DesignateZone, self).validate()

        def raise_invalid_exception(zone_type, prp):
            if self.properties.get(self.TYPE) == zone_type:
                if not self.properties.get(prp):
                    msg = _('Property %(prp)s is required for zone type '
                            '%(zone_type)s') % {
                        "prp": prp,
                        "zone_type": zone_type
                    }
                    raise exception.StackValidationFailed(message=msg)

        raise_invalid_exception(self.PRIMARY, self.EMAIL)
        raise_invalid_exception(self.SECONDARY, self.MASTERS)

    def handle_create(self):
        args = dict((k, v) for k, v in six.iteritems(self.properties) if v)
        args['type_'] = args.pop(self.TYPE)

        zone = self.client().zones.create(**args)

        self.resource_id_set(zone['id'])

    def _check_status_complete(self):
        zone = self.client().zones.get(self.resource_id)

        if zone['status'] == 'ERROR':
            raise exception.ResourceInError(
                resource_status=zone['status'],
                status_reason=_('Error in zone'))

        return zone['status'] != 'PENDING'

    def check_create_complete(self, handler_data=None):
        return self._check_status_complete()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        args = dict()

        for prp in (self.EMAIL, self.TTL, self.DESCRIPTION, self.MASTERS):
            if prop_diff.get(prp):
                args[prp] = prop_diff.get(prp)

        if len(args.keys()) > 0:
            self.client().zones.update(self.resource_id, args)

    def check_update_complete(self, handler_data=None):
        return self._check_status_complete()

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        if name == self.SERIAL:
            zone = self.client().zones.get(self.resource_id)
            return zone[name]

    def check_delete_complete(self, handler_data=None):
        if handler_data:
            with self.client_plugin().ignore_not_found:
                return self._check_status_complete()

        return True


def resource_mapping():
    return {
        'OS::Designate::Zone': DesignateZone
    }
