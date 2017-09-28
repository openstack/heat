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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class DesignateRecord(resource.Resource):
    """Heat Template Resource for Designate Record.

    Designate provides DNS-as-a-Service services for OpenStack. Record is
    storage unit in DNS. So, DNS name server is a server that stores the DNS
    records for a domain. Each record has a type and type-specific data.
    """

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='10.0.0',
        message=_('Use OS::Designate::RecordSet instead.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            version='8.0.0',
            previous_status=support.SupportStatus(version='5.0.0')))

    entity = 'records'

    default_client_name = 'designate'

    PROPERTIES = (
        NAME, TTL, DESCRIPTION, TYPE, DATA, PRIORITY, DOMAIN
    ) = (
        'name', 'ttl', 'description', 'type', 'data', 'priority', 'domain'
    )

    _ALLOWED_TYPES = (
        A, AAAA, CNAME, MX, SRV, TXT, SPF,
        NS, PTR, SSHFP, SOA
    ) = (
        'A', 'AAAA', 'CNAME', 'MX', 'SRV', 'TXT', 'SPF',
        'NS', 'PTR', 'SSHFP', 'SOA'
    )

    properties_schema = {
        # Based on RFC 1035, length of name is set to max of 255
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Record name.'),
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
            _('Description of record.'),
            update_allowed=True,
            constraints=[constraints.Length(max=160)]
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('DNS Record type.'),
            update_allowed=True,
            required=True,
            constraints=[constraints.AllowedValues(
                _ALLOWED_TYPES
            )]
        ),
        DATA: properties.Schema(
            properties.Schema.STRING,
            _('DNS record data, varies based on the type of record. For more '
              'details, please refer rfc 1035.'),
            update_allowed=True,
            required=True
        ),
        # Based on RFC 1035, range for priority is set to 0 to signed 16 bit
        # number
        PRIORITY: properties.Schema(
            properties.Schema.INTEGER,
            _('DNS record priority. It is considered only for MX and SRV '
              'types, otherwise, it is ignored.'),
            update_allowed=True,
            constraints=[constraints.Range(min=0,
                                           max=65536)]
        ),
        DOMAIN: properties.Schema(
            properties.Schema.STRING,
            _('DNS Domain id or name.'),
            required=True,
            constraints=[constraints.CustomConstraint('designate.domain')]
        ),
    }

    def handle_create(self):
        args = dict(
            name=self.properties[self.NAME],
            type=self.properties[self.TYPE],
            description=self.properties[self.DESCRIPTION],
            ttl=self.properties[self.TTL],
            data=self.properties[self.DATA],
            # priority is considered only for MX and SRV record.
            priority=(self.properties[self.PRIORITY]
                      if self.properties[self.TYPE] in (self.MX, self.SRV)
                      else None),
            domain=self.properties[self.DOMAIN]
        )

        domain = self.client_plugin().record_create(**args)

        self.resource_id_set(domain.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        args = dict()

        if prop_diff.get(self.TTL):
            args['ttl'] = prop_diff.get(self.TTL)

        if prop_diff.get(self.DESCRIPTION):
            args['description'] = prop_diff.get(self.DESCRIPTION)

        if prop_diff.get(self.TYPE):
            args['type'] = prop_diff.get(self.TYPE)

        # priority is considered only for MX and SRV record.
        if prop_diff.get(self.PRIORITY):
            args['priority'] = (prop_diff.get(self.PRIORITY)
                                if (prop_diff.get(self.TYPE) or
                                self.properties[self.TYPE]) in
                                (self.MX, self.SRV)
                                else None)

        if prop_diff.get(self.DATA):
            args['data'] = prop_diff.get(self.DATA)

        if len(args.keys()) > 0:
            args['id'] = self.resource_id
            args['domain'] = self.properties[self.DOMAIN]
            self.client_plugin().record_update(**args)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client_plugin().record_delete(
                    id=self.resource_id,
                    domain=self.properties[self.DOMAIN]
                )

    # FIXME(kanagaraj-manickam) Remove this method once designate defect
    # 1485552 is fixed.
    def _show_resource(self):
        kwargs = dict(domain=self.properties[self.DOMAIN],
                      id=self.resource_id)
        return dict(six.iteritems(self.client_plugin().record_show(**kwargs)))

    def parse_live_resource_data(self, resource_properties, resource_data):
        record_reality = {}

        properties_keys = list(set(self.PROPERTIES) - {self.NAME, self.DOMAIN})
        for key in properties_keys:
            record_reality.update({key: resource_data.get(key)})

        return record_reality


def resource_mapping():
    return {
        'OS::Designate::Record': DesignateRecord
    }
