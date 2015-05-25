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

import copy

from oslo_log import log as logging

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LW
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.nova import server


try:
    import pyrax  # noqa
    PYRAX_INSTALLED = True
except ImportError:
    PYRAX_INSTALLED = False

LOG = logging.getLogger(__name__)


class CloudServer(server.Server):
    """Resource for Rackspace Cloud Servers.

    This resource overloads existent integrated OS::Nova::Server resource and
    is used for Rackspace Cloud Servers.
    """

    # Managed Cloud automation statuses
    MC_STATUS_IN_PROGRESS = 'In Progress'
    MC_STATUS_COMPLETE = 'Complete'
    MC_STATUS_BUILD_ERROR = 'Build Error'

    # RackConnect automation statuses
    RC_STATUS_DEPLOYING = 'DEPLOYING'
    RC_STATUS_DEPLOYED = 'DEPLOYED'
    RC_STATUS_FAILED = 'FAILED'
    RC_STATUS_UNPROCESSABLE = 'UNPROCESSABLE'

    properties_schema = copy.deepcopy(server.Server.properties_schema)
    properties_schema.update(
        {
            server.Server.USER_DATA_FORMAT: properties.Schema(
                properties.Schema.STRING,
                _('How the user_data should be formatted for the server. For '
                  'HEAT_CFNTOOLS, the user_data is bundled as part of the '
                  'heat-cfntools cloud-init boot configuration data. For RAW '
                  'the user_data is passed to Nova unmodified. '
                  'For SOFTWARE_CONFIG user_data is bundled as part of the '
                  'software config data, and metadata is derived from any '
                  'associated SoftwareDeployment resources.'),
                default=server.Server.RAW,
                constraints=[
                    constraints.AllowedValues(
                        server.Server._SOFTWARE_CONFIG_FORMATS),
                ]
            ),
        }
    )

    def __init__(self, name, json_snippet, stack):
        super(CloudServer, self).__init__(name, json_snippet, stack)
        self._managed_cloud_started_event_sent = False
        self._rack_connect_started_event_sent = False

    def _config_drive(self):
        user_data = self.properties.get(self.USER_DATA)
        config_drive = self.properties.get(self.CONFIG_DRIVE)
        if user_data or config_drive:
            return True
        else:
            return False

    def _check_managed_cloud_complete(self, server):
        if not self._managed_cloud_started_event_sent:
            msg = _("Waiting for Managed Cloud automation to complete")
            self._add_event(self.action, self.status, msg)
            self._managed_cloud_started_event_sent = True

        if 'rax_service_level_automation' not in server.metadata:
            LOG.debug("Managed Cloud server does not have the "
                      "rax_service_level_automation metadata tag yet")
            return False

        mc_status = server.metadata['rax_service_level_automation']
        LOG.debug("Managed Cloud automation status: %s" % mc_status)

        if mc_status == self.MC_STATUS_IN_PROGRESS:
            return False

        elif mc_status == self.MC_STATUS_COMPLETE:
            msg = _("Managed Cloud automation has completed")
            self._add_event(self.action, self.status, msg)
            return True

        elif mc_status == self.MC_STATUS_BUILD_ERROR:
            raise exception.Error(_("Managed Cloud automation failed"))

        else:
            raise exception.Error(_("Unknown Managed Cloud automation "
                                    "status: %s") % mc_status)

    def _check_rack_connect_complete(self, server):
        if not self._rack_connect_started_event_sent:
            msg = _("Waiting for RackConnect automation to complete")
            self._add_event(self.action, self.status, msg)
            self._rack_connect_started_event_sent = True

        if 'rackconnect_automation_status' not in server.metadata:
            LOG.debug("RackConnect server does not have the "
                      "rackconnect_automation_status metadata tag yet")
            return False

        rc_status = server.metadata['rackconnect_automation_status']
        LOG.debug("RackConnect automation status: %s" % rc_status)

        if rc_status == self.RC_STATUS_DEPLOYING:
            return False

        elif rc_status == self.RC_STATUS_DEPLOYED:
            self._server = None  # The public IP changed, forget old one
            return True

        elif rc_status == self.RC_STATUS_UNPROCESSABLE:
            # UNPROCESSABLE means the RackConnect automation was not
            # attempted (eg. Cloud Server in a different DC than
            # dedicated gear, so RackConnect does not apply).  It is
            # okay if we do not raise an exception.
            reason = server.metadata.get('rackconnect_unprocessable_reason',
                                         None)
            if reason is not None:
                LOG.warn(_LW("RackConnect unprocessable reason: %s"), reason)

            msg = _("RackConnect automation has completed")
            self._add_event(self.action, self.status, msg)
            return True

        elif rc_status == self.RC_STATUS_FAILED:
            raise exception.Error(_("RackConnect automation FAILED"))

        else:
            msg = _("Unknown RackConnect automation status: %s") % rc_status
            raise exception.Error(msg)

    def check_create_complete(self, server):
        """Check if server creation is complete and handle server configs."""
        if not super(CloudServer, self).check_create_complete(server):
            return False

        self.client_plugin().refresh_server(server)

        if ('rack_connect' in self.context.roles and not
                self._check_rack_connect_complete(server)):
            return False

        if ('rax_managed' in self.context.roles and not
                self._check_managed_cloud_complete(server)):
            return False

        return True


def resource_mapping():
    return {'OS::Nova::Server': CloudServer}


def available_resource_mapping():
    if PYRAX_INSTALLED:
        return resource_mapping()
    return {}
