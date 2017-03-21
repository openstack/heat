#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
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

from oslo_log import log as logging
from oslo_utils import encodeutils
import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support

LOG = logging.getLogger(__name__)


class ManilaShare(resource.Resource):
    """A resource that creates shared mountable file system.

    The resource creates a manila share - shared mountable filesystem that
    can be attached to any client(or clients) that has a network access and
    permission to mount filesystem. Share is a unit of storage with specific
    size that supports pre-defined share protocol and advanced security model
    (access lists, share networks and security services).
    """

    support_status = support.SupportStatus(version='5.0.0')

    _ACCESS_RULE_PROPERTIES = (
        ACCESS_TO, ACCESS_TYPE, ACCESS_LEVEL
    ) = (
        'access_to', 'access_type', 'access_level')

    _SHARE_STATUSES = (
        STATUS_CREATING, STATUS_DELETING, STATUS_ERROR, STATUS_ERROR_DELETING,
        STATUS_AVAILABLE
    ) = (
        'creating', 'deleting', 'error', 'error_deleting',
        'available'
    )

    PROPERTIES = (
        SHARE_PROTOCOL, SIZE, SHARE_SNAPSHOT, NAME, METADATA,
        SHARE_NETWORK, DESCRIPTION, SHARE_TYPE, IS_PUBLIC,
        ACCESS_RULES
    ) = (
        'share_protocol', 'size', 'snapshot', 'name', 'metadata',
        'share_network', 'description', 'share_type', 'is_public',
        'access_rules'
    )

    ATTRIBUTES = (
        AVAILABILITY_ZONE_ATTR, HOST_ATTR, EXPORT_LOCATIONS_ATTR,
        SHARE_SERVER_ID_ATTR, CREATED_AT_ATTR, SHARE_STATUS_ATTR,
        PROJECT_ID_ATTR
    ) = (
        'availability_zone', 'host', 'export_locations',
        'share_server_id', 'created_at', 'status',
        'project_id'
    )

    properties_schema = {
        SHARE_PROTOCOL: properties.Schema(
            properties.Schema.STRING,
            _('Share protocol supported by shared filesystem.'),
            required=True,
            constraints=[constraints.AllowedValues(
                ['NFS', 'CIFS', 'GlusterFS', 'HDFS', 'CEPHFS'])]
        ),
        SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('Share storage size in GB.'),
            required=True
        ),
        SHARE_SNAPSHOT: properties.Schema(
            properties.Schema.STRING,
            _('Name or ID of shared file system snapshot that '
              'will be restored and created as a new share.'),
            constraints=[constraints.CustomConstraint('manila.share_snapshot')]
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Share name.'),
            update_allowed=True
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Metadata key-values defined for share.'),
            update_allowed=True
        ),
        SHARE_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('Name or ID of shared network defined for shared filesystem.'),
            constraints=[constraints.CustomConstraint('manila.share_network')]
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Share description.'),
            update_allowed=True
        ),
        SHARE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Name or ID of shared filesystem type. Types defines some share '
              'filesystem profiles that will be used for share creation.'),
            constraints=[constraints.CustomConstraint("manila.share_type")]
        ),
        IS_PUBLIC: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Defines if shared filesystem is public or private.'),
            default=False,
            update_allowed=True
        ),
        ACCESS_RULES: properties.Schema(
            properties.Schema.LIST,
            _('A list of access rules that define access from IP to Share.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    ACCESS_TO: properties.Schema(
                        properties.Schema.STRING,
                        _('IP or other address information about guest that '
                          'allowed to access to Share.'),
                        required=True
                    ),
                    ACCESS_TYPE: properties.Schema(
                        properties.Schema.STRING,
                        _('Type of access that should be provided to guest.'),
                        constraints=[constraints.AllowedValues(
                            ['ip', 'user', 'cert', 'cephx'])],
                        required=True
                    ),
                    ACCESS_LEVEL: properties.Schema(
                        properties.Schema.STRING,
                        _('Level of access that need to be provided for '
                          'guest.'),
                        constraints=[constraints.AllowedValues(['ro', 'rw'])]
                    )
                }
            ),
            update_allowed=True,
            default=[]
        )
    }

    attributes_schema = {
        AVAILABILITY_ZONE_ATTR: attributes.Schema(
            _('The availability zone of shared filesystem.'),
            type=attributes.Schema.STRING
        ),
        HOST_ATTR: attributes.Schema(
            _('Share host.'),
            type=attributes.Schema.STRING
        ),
        EXPORT_LOCATIONS_ATTR: attributes.Schema(
            _('Export locations of share.'),
            type=attributes.Schema.LIST
        ),
        SHARE_SERVER_ID_ATTR: attributes.Schema(
            _('ID of server (VM, etc...) on host that is used for '
              'exporting network file-system.'),
            type=attributes.Schema.STRING
        ),
        CREATED_AT_ATTR: attributes.Schema(
            _('Datetime when a share was created.'),
            type=attributes.Schema.STRING
        ),
        SHARE_STATUS_ATTR: attributes.Schema(
            _('Current share status.'),
            type=attributes.Schema.STRING
        ),
        PROJECT_ID_ATTR: attributes.Schema(
            _('Share project ID.'),
            type=attributes.Schema.STRING
        )
    }

    default_client_name = 'manila'

    entity = 'shares'

    def _request_share(self):
        return self.client().shares.get(self.resource_id)

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        share = self._request_share()
        return six.text_type(getattr(share, name))

    def handle_create(self):
        # Request IDs of entities from manila
        # if name of the entity defined in template
        share_net_identity = self.properties[self.SHARE_NETWORK]
        if share_net_identity:
            share_net_identity = self.client_plugin().get_share_network(
                share_net_identity).id
        snapshot_identity = self.properties[self.SHARE_SNAPSHOT]
        if snapshot_identity:
            snapshot_identity = self.client_plugin().get_share_snapshot(
                snapshot_identity).id
        share_type_identity = self.properties[self.SHARE_TYPE]
        if share_type_identity:
            share_type_identity = self.client_plugin().get_share_type(
                share_type_identity).id

        share = self.client().shares.create(
            share_proto=self.properties[self.SHARE_PROTOCOL],
            size=self.properties[self.SIZE],
            snapshot_id=snapshot_identity,
            name=self.properties[self.NAME],
            description=self.properties[self.DESCRIPTION],
            metadata=self.properties[self.METADATA],
            share_network=share_net_identity,
            share_type=share_type_identity,
            is_public=self.properties[self.IS_PUBLIC])

        self.resource_id_set(share.id)

    def check_create_complete(self, *args):
        share_status = self._request_share().status
        if share_status == self.STATUS_CREATING:
            return False
        elif share_status == self.STATUS_AVAILABLE:
            LOG.info('Applying access rules to created Share.')
            # apply access rules to created share. please note that it is not
            # possible to define rules for share with share_status = creating
            access_rules = self.properties.get(self.ACCESS_RULES)
            try:
                if access_rules:
                    for rule in access_rules:
                        self.client().shares.allow(
                            share=self.resource_id,
                            access_type=rule.get(self.ACCESS_TYPE),
                            access=rule.get(self.ACCESS_TO),
                            access_level=rule.get(self.ACCESS_LEVEL))
                return True
            except Exception as ex:
                err_msg = encodeutils.exception_to_unicode(ex)
                reason = _(
                    'Error during applying access rules to share "{0}". '
                    'The root cause of the problem is the following: {1}.'
                ).format(self.resource_id, err_msg)
                raise exception.ResourceInError(
                    status_reason=reason, resource_status=share_status)
        elif share_status == self.STATUS_ERROR:
            reason = _('Error during creation of share "{0}"').format(
                self.resource_id)
            raise exception.ResourceInError(status_reason=reason,
                                            resource_status=share_status)
        else:
            reason = _('Unknown share_status during creation of share "{0}"'
                       ).format(self.resource_id)
            raise exception.ResourceUnknownStatus(
                status_reason=reason, resource_status=share_status)

    def check_delete_complete(self, *args):
        if not self.resource_id:
            return True

        try:
            share = self._request_share()
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            return True
        else:
            # when share creation is not finished proceed listening
            if share.status == self.STATUS_DELETING:
                return False
            elif share.status in (self.STATUS_ERROR,
                                  self.STATUS_ERROR_DELETING):
                raise exception.ResourceInError(
                    status_reason=_(
                        'Error during deleting share "{0}".'
                    ).format(self.resource_id),
                    resource_status=share.status)
            else:
                reason = _('Unknown status during deleting share '
                           '"{0}"').format(self.resource_id)
                raise exception.ResourceUnknownStatus(
                    status_reason=reason, resource_status=share.status)

    def handle_check(self):
        share = self._request_share()
        expected_statuses = [self.STATUS_AVAILABLE]
        checks = [{'attr': 'status', 'expected': expected_statuses,
                   'current': share.status}]
        self._verify_check_conditions(checks)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        kwargs = {}
        if self.IS_PUBLIC in prop_diff:
            kwargs['is_public'] = prop_diff.get(self.IS_PUBLIC)
        if self.NAME in prop_diff:
            kwargs['display_name'] = prop_diff.get(self.NAME)
        if self.DESCRIPTION in prop_diff:
            kwargs['display_description'] = prop_diff.get(self.DESCRIPTION)
        if kwargs:
            self.client().shares.update(self.resource_id,
                                        **kwargs)

        if self.METADATA in prop_diff:
            metadata = prop_diff.get(self.METADATA)
            self.client().shares.update_all_metadata(
                self.resource_id, metadata)

        if self.ACCESS_RULES in prop_diff:
            actual_old_rules = []
            for rule in self.client().shares.access_list(self.resource_id):
                old_rule = {
                    self.ACCESS_TO: getattr(rule, self.ACCESS_TO),
                    self.ACCESS_TYPE: getattr(rule, self.ACCESS_TYPE),
                    self.ACCESS_LEVEL: getattr(rule, self.ACCESS_LEVEL)
                }
                if old_rule in prop_diff[self.ACCESS_RULES]:
                    actual_old_rules.append(old_rule)
                else:
                    self.client().shares.deny(share=self.resource_id,
                                              id=rule.id)
            for rule in prop_diff[self.ACCESS_RULES]:
                if rule not in actual_old_rules:
                    self.client().shares.allow(
                        share=self.resource_id,
                        access_type=rule.get(self.ACCESS_TYPE),
                        access=rule.get(self.ACCESS_TO),
                        access_level=rule.get(self.ACCESS_LEVEL)
                    )

    def parse_live_resource_data(self, resource_properties, resource_data):
        result = super(ManilaShare, self).parse_live_resource_data(
            resource_properties, resource_data)

        rules = self.client().shares.access_list(self.resource_id)
        result[self.ACCESS_RULES] = []
        for rule in rules:
            result[self.ACCESS_RULES].append(
                {(k, v) for (k, v) in six.iteritems(rule)
                 if k in self._ACCESS_RULE_PROPERTIES})
        return result


def resource_mapping():
    return {'OS::Manila::Share': ManilaShare}
