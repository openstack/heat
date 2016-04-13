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
from heat.engine import support


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

    support_status = support.SupportStatus(
        status=support.UNSUPPORTED,
        message=_('This resource is not supported, use at your own risk.'))

    # Rackspace Cloud automation statuses
    SM_STATUS_IN_PROGRESS = 'In Progress'
    SM_STATUS_COMPLETE = 'Complete'
    SM_STATUS_BUILD_ERROR = 'Build Error'

    # RackConnect automation statuses
    RC_STATUS_DEPLOYING = 'DEPLOYING'
    RC_STATUS_DEPLOYED = 'DEPLOYED'
    RC_STATUS_FAILED = 'FAILED'
    RC_STATUS_UNPROCESSABLE = 'UNPROCESSABLE'

    # Nova Extra specs
    FLAVOR_EXTRA_SPECS = 'OS-FLV-WITH-EXT-SPECS:extra_specs'
    FLAVOR_CLASSES_KEY = 'flavor_classes'
    FLAVOR_ACCEPT_ANY = '*'
    FLAVOR_CLASS = 'class'
    DISK_IO_INDEX = 'disk_io_index'
    FLAVOR_CLASSES = (
        GENERAL1, MEMORY1, PERFORMANCE2, PERFORMANCE1, STANDARD1, IO1,
        ONMETAL, COMPUTE1
    ) = (
        'general1', 'memory1', 'performance2', 'performance1',
        'standard1', 'io1', 'onmetal', 'compute1',
    )
    BASE_IMAGE_REF = 'base_image_ref'

    # flavor classes that can be booted ONLY from volume
    BFV_VOLUME_REQUIRED = {MEMORY1, COMPUTE1}

    # flavor classes that can NOT be booted from volume
    NON_BFV = {STANDARD1, ONMETAL}

    properties_schema = copy.deepcopy(server.Server.properties_schema)
    properties_schema.update(
        {
            server.Server.USER_DATA_FORMAT: properties.Schema(
                properties.Schema.STRING,
                _('How the user_data should be formatted for the server. '
                  'For RAW the user_data is passed to Nova unmodified. '
                  'For SOFTWARE_CONFIG user_data is bundled as part of the '
                  'software config data, and metadata is derived from any '
                  'associated SoftwareDeployment resources.'),
                default=server.Server.RAW,
                constraints=[
                    constraints.AllowedValues([
                        server.Server.RAW, server.Server.SOFTWARE_CONFIG
                    ])
                ]
            ),
        }
    )
    properties_schema.update(
        {
            server.Server.SOFTWARE_CONFIG_TRANSPORT: properties.Schema(
                properties.Schema.STRING,
                _('How the server should receive the metadata required for '
                  'software configuration. POLL_TEMP_URL is the only '
                  'supported transport on Rackspace Cloud. This property is '
                  'retained for compatability.'),
                default=server.Server.POLL_TEMP_URL,
                update_allowed=True,
                constraints=[
                    constraints.AllowedValues([
                        server.Server.POLL_TEMP_URL
                    ])
                ]
            ),
        }
    )

    def __init__(self, name, json_snippet, stack):
        super(CloudServer, self).__init__(name, json_snippet, stack)
        self._managed_cloud_started_event_sent = False
        self._rack_connect_started_event_sent = False

    def _config_drive(self):
        user_data_format = self.properties.get(self.USER_DATA_FORMAT, "")
        is_sw_config = user_data_format == self.SOFTWARE_CONFIG
        user_data = self.properties.get(self.USER_DATA)
        config_drive = self.properties.get(self.CONFIG_DRIVE)
        if config_drive or is_sw_config or user_data:
            return True
        else:
            return False

    def _check_rax_automation_complete(self, server):
        if not self._managed_cloud_started_event_sent:
            msg = _("Waiting for Rackspace Cloud automation to complete")
            self._add_event(self.action, self.status, msg)
            self._managed_cloud_started_event_sent = True

        if 'rax_service_level_automation' not in server.metadata:
            LOG.debug("Cloud server does not have the "
                      "rax_service_level_automation metadata tag yet")
            return False

        mc_status = server.metadata['rax_service_level_automation']
        LOG.debug("Rackspace Cloud automation status: %s" % mc_status)

        if mc_status == self.SM_STATUS_IN_PROGRESS:
            return False

        elif mc_status == self.SM_STATUS_COMPLETE:
            msg = _("Rackspace Cloud automation has completed")
            self._add_event(self.action, self.status, msg)
            return True

        elif mc_status == self.SM_STATUS_BUILD_ERROR:
            raise exception.Error(_("Rackspace Cloud automation failed"))

        else:
            raise exception.Error(_("Unknown Rackspace Cloud automation "
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
                LOG.warning(_LW("RackConnect unprocessable reason: %s"),
                            reason)

            msg = _("RackConnect automation has completed")
            self._add_event(self.action, self.status, msg)
            return True

        elif rc_status == self.RC_STATUS_FAILED:
            raise exception.Error(_("RackConnect automation FAILED"))

        else:
            msg = _("Unknown RackConnect automation status: %s") % rc_status
            raise exception.Error(msg)

    def check_create_complete(self, server_id):
        """Check if server creation is complete and handle server configs."""
        if not super(CloudServer, self).check_create_complete(server_id):
            return False

        server = self.client_plugin().fetch_server(server_id)
        if not server:
            return False

        if ('rack_connect' in self.context.roles and not
                self._check_rack_connect_complete(server)):
            return False

        if not self._check_rax_automation_complete(server):
            return False

        return True

    # Since rackspace compute service does not support 'os-interface' endpoint,
    # accessing addresses attribute of OS::Nova::Server results in NotFound
    # error. Here overrdiing '_add_port_for_address' method and using different
    # endpoint named 'os-virtual-interfacesv2' to get the same information.
    def _add_port_for_address(self, server):
        def get_port(net_name, address):
            for iface in ifaces:
                for ip_addr in iface.ip_addresses:
                    if ip_addr['network_label'] == net_name and ip_addr[
                            'address'] == address:
                        return iface.id

        nets = copy.deepcopy(server.addresses)
        nova_ext = self.client().os_virtual_interfacesv2_python_novaclient_ext
        ifaces = nova_ext.list(server.id)
        for net_name, addresses in nets.items():
            for address in addresses:
                address['port'] = get_port(net_name, address['addr'])

        return self._extend_networks(nets)

    def _base_image_obj(self, image):
        image_obj = self.client_plugin('glance').get_image(image)
        if self.BASE_IMAGE_REF in image_obj:
            base_image = image_obj[self.BASE_IMAGE_REF]
            return self.client_plugin('glance').get_image(base_image)
        return image_obj

    def _image_flavor_class_match(self, flavor_type, image):
        base_image_obj = self._base_image_obj(image)
        flavor_class_string = base_image_obj.get(self.FLAVOR_CLASSES_KEY)

        # If the flavor_class_string metadata does not exist or is
        # empty, do not validate image/flavor combo
        if not flavor_class_string:
            return True

        flavor_class_excluded = "!{0}".format(flavor_type)
        flavor_classes_accepted = flavor_class_string.split(',')

        if flavor_type in flavor_classes_accepted:
            return True

        if (self.FLAVOR_ACCEPT_ANY in flavor_classes_accepted and
           flavor_class_excluded not in flavor_classes_accepted):
            return True

        return False

    def validate(self):
        """Validate for Rackspace Cloud specific parameters"""
        super(CloudServer, self).validate()

        # check if image, flavor combination is valid
        flavor = self.properties[self.FLAVOR]
        flavor_obj = self.client_plugin().get_flavor(flavor)
        fl_xtra_specs = flavor_obj.to_dict().get(self.FLAVOR_EXTRA_SPECS, {})
        flavor_type = fl_xtra_specs.get(self.FLAVOR_CLASS, None)

        image = self.properties.get(self.IMAGE)
        if not image:
            if flavor_type in self.NON_BFV:
                msg = _('Flavor %s cannot be booted from volume.') % flavor
                raise exception.StackValidationFailed(message=msg)
            else:
                # we cannot determine details of the attached volume, so this
                # is all the validation possible
                return

        if not self._image_flavor_class_match(flavor_type, image):
            msg = _('Flavor %(flavor)s cannot be used with image '
                    '%(image)s.') % {'image': image, 'flavor': flavor}
            raise exception.StackValidationFailed(message=msg)

        if flavor_type in self.BFV_VOLUME_REQUIRED:
            msg = _('Flavor %(flavor)s must be booted from volume, '
                    'but image %(image)s was also specified.') % {
                'flavor': flavor, 'image': image}
            raise exception.StackValidationFailed(message=msg)


def resource_mapping():
    return {'OS::Nova::Server': CloudServer}


def available_resource_mapping():
    if PYRAX_INSTALLED:
        return resource_mapping()
    return {}
