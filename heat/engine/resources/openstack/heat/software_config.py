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
from heat.engine import properties
from heat.engine import resource
from heat.engine import software_config_io as swc_io
from heat.engine import support
from heat.rpc import api as rpc_api


class SoftwareConfig(resource.Resource):
    """A resource for describing and storing software configuration.

    The software_configs API which backs this resource creates immutable
    configs, so any change to the template resource definition will result
    in a new config being created, and the old one being deleted.

    Configs can be defined in the same template which uses them, or they can
    be created in one stack, and passed to another stack via a parameter.

    A config resource can be referenced in other resource properties which
    are config-aware. This includes the properties OS::Nova::Server user_data,
    OS::Heat::SoftwareDeployment config and OS::Heat::MultipartMime parts
    config.

    Along with the config script itself, this resource can define schemas for
    inputs and outputs which the config script is expected to consume and
    produce. Inputs and outputs are optional and will map to concepts which
    are specific to the configuration tool being used.
    """

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        GROUP, CONFIG,
        OPTIONS,
        INPUTS, OUTPUTS
    ) = (
        rpc_api.SOFTWARE_CONFIG_GROUP, rpc_api.SOFTWARE_CONFIG_CONFIG,
        rpc_api.SOFTWARE_CONFIG_OPTIONS,
        rpc_api.SOFTWARE_CONFIG_INPUTS, rpc_api.SOFTWARE_CONFIG_OUTPUTS,
    )

    ATTRIBUTES = (
        CONFIG_ATTR,
    ) = (
        'config',
    )

    properties_schema = {
        GROUP: properties.Schema(
            properties.Schema.STRING,
            _('Namespace to group this software config by when delivered to '
              'a server. This may imply what configuration tool is going to '
              'perform the configuration.'),
            default='Heat::Ungrouped'
        ),
        CONFIG: properties.Schema(
            properties.Schema.STRING,
            _('Configuration script or manifest which specifies what actual '
              'configuration is performed.'),
        ),
        OPTIONS: properties.Schema(
            properties.Schema.MAP,
            _('Map containing options specific to the configuration '
              'management tool used by this resource.'),
        ),
        INPUTS: properties.Schema(
            properties.Schema.LIST,
            _('Schema representing the inputs that this software config is '
              'expecting.'),
            schema=properties.Schema(properties.Schema.MAP,
                                     schema=swc_io.input_config_schema)
        ),
        OUTPUTS: properties.Schema(
            properties.Schema.LIST,
            _('Schema representing the outputs that this software config '
              'will produce.'),
            schema=properties.Schema(properties.Schema.MAP,
                                     schema=swc_io.output_config_schema)
        ),
    }

    attributes_schema = {
        CONFIG_ATTR: attributes.Schema(
            _("The config value of the software config."),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        props = dict(self.properties)
        props[rpc_api.SOFTWARE_CONFIG_NAME] = self.physical_resource_name()

        sc = self.rpc_client().create_software_config(self.context, **props)
        self.resource_id_set(sc[rpc_api.SOFTWARE_CONFIG_ID])

    def handle_delete(self):

        if self.resource_id is None:
            return

        with self.rpc_client().ignore_error_by_name('NotFound'):
            self.rpc_client().delete_software_config(
                self.context, self.resource_id)

    def _resolve_attribute(self, name):
        """Retrieve attributes of the SoftwareConfig resource.

        "config" returns the config value of the software config. If the
         software config does not exist, returns an empty string.
        """
        if name == self.CONFIG_ATTR and self.resource_id:
            with self.rpc_client().ignore_error_by_name('NotFound'):
                sc = self.rpc_client().show_software_config(
                    self.context, self.resource_id)
                return sc[rpc_api.SOFTWARE_CONFIG_CONFIG]


def resource_mapping():
    return {
        'OS::Heat::SoftwareConfig': SoftwareConfig,
    }
