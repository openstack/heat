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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class DesignateRecordSet(resource.Resource):
    """Heat Template Resource for Designate RecordSet.

    Designate provides DNS-as-a-Service services for OpenStack. RecordSet
    helps to add more than one records.
    """

    support_status = support.SupportStatus(
        version='8.0.0')

    PROPERTIES = (
        NAME, TTL, DESCRIPTION, TYPE, RECORDS, ZONE
    ) = (
        'name', 'ttl', 'description', 'type', 'records', 'zone'
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
            _('RecordSet name.'),
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
            _('Description of RecordSet.'),
            update_allowed=True,
            constraints=[constraints.Length(max=160)]
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('DNS RecordSet type.'),
            required=True,
            constraints=[constraints.AllowedValues(
                _ALLOWED_TYPES
            )]
        ),
        RECORDS: properties.Schema(
            properties.Schema.LIST,
            _('A list of data for this RecordSet. Each item will be a '
              'separate record in Designate These items should conform to the '
              'DNS spec for the record type - e.g. A records must be IPv4 '
              'addresses, CNAME records must be a hostname. DNS record data '
              'varies based on the type of record. For more details, please '
              'refer rfc 1035.'),
            update_allowed=True,
            required=True
        ),
        ZONE: properties.Schema(
            properties.Schema.STRING,
            _('DNS Zone id or name.'),
            required=True,
            constraints=[constraints.CustomConstraint('designate.zone')]
        ),
    }

    default_client_name = 'designate'

    entity = 'recordsets'

    def client(self):
        return super(DesignateRecordSet,
                     self).client(version=self.client_plugin().V2)

    def handle_create(self):
        args = dict((k, v) for k, v in six.iteritems(self.properties) if v)
        args['type_'] = args.pop(self.TYPE)
        if not args.get(self.NAME):
            args[self.NAME] = self.physical_resource_name()

        rs = self.client().recordsets.create(**args)

        self.resource_id_set(rs['id'])

    def _check_status_complete(self):
        recordset = self.client().recordsets.get(
            recordset=self.resource_id,
            zone=self.properties[self.ZONE]
        )

        if recordset['status'] == 'ERROR':
            raise exception.ResourceInError(
                resource_status=recordset['status'],
                status_reason=_('Error in RecordSet'))

        return recordset['status'] != 'PENDING'

    def check_create_complete(self, handler_data=None):
        return self._check_status_complete()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        args = dict()

        for prp in (self.TTL, self.DESCRIPTION, self.RECORDS):
            if prop_diff.get(prp):
                args[prp] = prop_diff.get(prp)

        if prop_diff.get(self.TYPE):
            args['type_'] = prop_diff.get(self.TYPE)

        if len(args.keys()) > 0:
            self.client().recordsets.update(
                recordset=self.resource_id,
                zone=self.properties[self.ZONE],
                values=args)

    def check_update_complete(self, handler_data=None):
        return self._check_status_complete()

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client().recordsets.delete(
                    recordset=self.resource_id,
                    zone=self.properties[self.ZONE]
                )

    def check_delete_complete(self, handler_data=None):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                return self._check_status_complete()

        return True

    def _show_resource(self):
        return self.client().recordsets.get(
            recordset=self.resource_id,
            zone=self.properties[self.ZONE]
        )


def resource_mapping():
    return {
        'OS::Designate::RecordSet': DesignateRecordSet
    }
