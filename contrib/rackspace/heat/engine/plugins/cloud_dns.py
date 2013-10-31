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

try:
    from pyrax.exceptions import NotFound
except ImportError:
    #Setup fake exception for testing without pyrax
    class NotFound(Exception):
        pass


from heat.common import exception
from heat.openstack.common import log as logging

from . import rackspace_resource

logger = logging.getLogger(__name__)


class CloudDns(rackspace_resource.RackspaceResource):

    record_schema = {
        'name': {
            'Type': 'String',
            'Required': True,
            'Description': _('Specifies the name for the domain or subdomain. '
                             'Must be a valid domain name.'),
            'MinLength': 3
        },
        'type': {
            'Type': 'String',
            'Required': True,
            'Description': _('Specifies the record type.'),
            'AllowedValues': [
                'A',
                'AAAA',
                'NS',
                'MX',
                'CNAME',
                'TXT',
                'SRV'
            ]
        },
        'data': {
            'Type': 'String',
            'Description': _('Type specific record data'),
            'Required': True
        },
        'ttl': {
            'Type': 'Integer',
            'Description': _('How long other servers should cache record'
                             'data.'),
            'MinValue': 301,
            'Default': 3600
        },
        'priority': {
            'Type': 'Integer',
            'Description': _('Required for MX and SRV records, but forbidden '
                             'for other record types. If specified, must be '
                             'an integer from 0 to 65535.'),
            'MinValue': 0,
            'MaxValue': 65535
        },
        'comment': {
            'Type': 'String',
            'Description': _('Optional free form text comment'),
            'MaxLength': 160
        }
    }

    properties_schema = {
        'name': {
            'Type': 'String',
            'Description': _('Specifies the name for the domain or subdomain. '
                             'Must be a valid domain name.'),
            'Required': True,
            'MinLength': 3
        },
        'emailAddress': {
            'Type': 'String',
            'UpdateAllowed': True,
            'Description': _('Email address to use for contacting the domain '
                             'administrator.'),
            'Required': True
        },
        'ttl': {
            'Type': 'Integer',
            'UpdateAllowed': True,
            'Description': _('How long other servers should cache record'
                             'data.'),
            'MinValue': 301,
            'Default': 3600
        },
        'comment': {
            'Type': 'String',
            'UpdateAllowed': True,
            'Description': _('Optional free form text comment'),
            'MaxLength': 160
        },
        'records': {
            'Type': 'List',
            'UpdateAllowed': True,
            'Description': _('Domain records'),
            'Schema': {
                'Type': 'Map',
                'Schema': record_schema
            }
        }
    }

    update_allowed_keys = ('Properties',)

    def handle_create(self):
        """
        Create a Rackspace CloudDns Instance.
        """
        # There is no check_create_complete as the pyrax create for DNS is
        # synchronous.
        logger.debug("CloudDns handle_create called.")
        args = dict((k, v) for k, v in self.properties.items())
        for rec in args['records'] or {}:
            # only pop the priority for the correct types
            if (rec['type'] != 'MX') and (rec['type'] != 'SRV'):
                rec.pop('priority', None)
        dom = self.cloud_dns().create(**args)
        self.resource_id_set(dom.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """
        Update a Rackspace CloudDns Instance.
        """
        logger.debug("CloudDns handle_update called.")
        if not self.resource_id:
            raise exception.Error('Update called on a non-existent domain')
        if prop_diff:
            dom = self.cloud_dns().get(self.resource_id)

            # handle records separately
            records = prop_diff.pop('records', {})

            # Handle top level domain properties
            dom.update(**prop_diff)

        # handle records
        if records:
            recs = dom.list_records()
            # 1. delete all the current records other than rackspace NS records
            [rec.delete() for rec in recs if rec.type != 'NS' or
                'stabletransit.com' not in rec.data]
            # 2. update with the new records in prop_diff
            dom.add_records(records)

    def handle_delete(self):
        """
        Delete a Rackspace CloudDns Instance.
        """
        logger.debug("CloudDns handle_delete called.")
        if self.resource_id:
            try:
                dom = self.cloud_dns().get(self.resource_id)
                dom.delete()
            except NotFound:
                pass
        self.resource_id_set(None)


# pyrax module is required to work with Rackspace cloud server provider.
# If it is not installed, don't register cloud server provider
def resource_mapping():
    if rackspace_resource.PYRAX_INSTALLED:
        return {'Rackspace::Cloud::DNS': CloudDns}
    else:
        return {}
