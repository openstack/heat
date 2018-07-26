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


class Bay(resource.Resource):
    """A resource that creates a Magnum Bay.

    This resource has been deprecated in favor of OS::Magnum::Cluster.
    """

    deprecation_msg = _('Please use OS::Magnum::Cluster instead.')
    support_status = support.SupportStatus(
        status=support.HIDDEN,
        message=deprecation_msg,
        version='11.0.0',
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=deprecation_msg,
            version='9.0.0',
            previous_status=support.SupportStatus(
                status=support.SUPPORTED,
                version='6.0.0')
        )
    )

    PROPERTIES = (
        NAME, BAYMODEL, NODE_COUNT, MASTER_COUNT, DISCOVERY_URL,
        BAY_CREATE_TIMEOUT
    ) = (
        'name', 'baymodel', 'node_count', 'master_count',
        'discovery_url', 'bay_create_timeout'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The bay name.')
        ),
        BAYMODEL: properties.Schema(
            properties.Schema.STRING,
            _('The name or ID of the bay model.'),
            constraints=[
                constraints.CustomConstraint('magnum.baymodel')
            ],
            required=True
        ),
        NODE_COUNT: properties.Schema(
            properties.Schema.INTEGER,
            _('The node count for this bay.'),
            constraints=[constraints.Range(min=1)],
            update_allowed=True,
            default=1
        ),
        MASTER_COUNT: properties.Schema(
            properties.Schema.INTEGER,
            _('The number of master nodes for this bay.'),
            constraints=[constraints.Range(min=1)],
            update_allowed=True,
            default=1
        ),
        DISCOVERY_URL: properties.Schema(
            properties.Schema.STRING,
            _('Specifies a custom discovery url for node discovery.')
        ),
        BAY_CREATE_TIMEOUT: properties.Schema(
            properties.Schema.INTEGER,
            _('Timeout for creating the bay in minutes. '
              'Set to 0 for no timeout.'),
            constraints=[constraints.Range(min=0)],
            default=0
        )
    }

    default_client_name = 'magnum'

    entity = 'bays'

    def handle_create(self):
        args = {
            'name': self.properties[self.NAME],
            'baymodel_id': self.properties[self.BAYMODEL],
            'node_count': self.properties[self.NODE_COUNT],
            'master_count': self.properties[self.NODE_COUNT],
            'discovery_url': self.properties[self.DISCOVERY_URL],
            'bay_create_timeout': self.properties[self.BAY_CREATE_TIMEOUT]
        }
        bay = self.client().bays.create(**args)
        self.resource_id_set(bay.uuid)
        return bay.uuid

    def check_create_complete(self, id):
        bay = self.client().bays.get(id)
        if bay.status == 'CREATE_IN_PROGRESS':
            return False
        elif bay.status is None:
            return False
        elif bay.status == 'CREATE_COMPLETE':
            return True
        elif bay.status == 'CREATE_FAILED':
            msg = (_("Failed to create Bay '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': bay.status_reason})
            raise exception.ResourceInError(status_reason=msg,
                                            resource_status=bay.status)
        else:
            msg = (_("Unknown status creating Bay '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': bay.status_reason})
            raise exception.ResourceUnknownStatus(status_reason=msg,
                                                  resource_status=bay.status)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            patch = [{'op': 'replace', 'path': '/' + k, 'value': v}
                     for k, v in six.iteritems(prop_diff)]
            self.client().bays.update(self.resource_id, patch)
            return self.resource_id

    def parse_live_resource_data(self, resource_properties, resource_data):
        record_reality = {}

        for key in [self.NODE_COUNT, self.MASTER_COUNT]:
            record_reality.update({key: resource_data.get(key)})

        return record_reality

    def check_update_complete(self, id):
        bay = self.client().bays.get(id)
        # Check update complete request might get status before the status
        # got changed to update in progress, so we allow `CREATE_COMPLETE`
        # for it.
        if bay.status in ['UPDATE_IN_PROGRESS', 'CREATE_COMPLETE']:
            return False
        elif bay.status == 'UPDATE_COMPLETE':
            return True
        elif bay.status == 'UPDATE_FAILED':
            msg = (_("Failed to update Bay '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': bay.status_reason})
            raise exception.ResourceInError(status_reason=msg,
                                            resource_status=bay.status)

        else:
            msg = (_("Unknown status updating Bay '%(name)s' - %(reason)s")
                   % {'name': self.name, 'reason': bay.status_reason})
            raise exception.ResourceUnknownStatus(status_reason=msg,
                                                  resource_status=bay.status)

    def check_delete_complete(self, id):
        if not id:
            return True
        try:
            self.client().bays.get(id)
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)
            return True
        return False


def resource_mapping():
    return {
        'OS::Magnum::Bay': Bay
    }
