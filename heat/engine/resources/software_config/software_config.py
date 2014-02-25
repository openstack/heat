
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

from heat.common import exception
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

import heatclient.exc as heat_exp

logger = logging.getLogger(__name__)


class SoftwareConfig(resource.Resource):

    PROPERTIES = (
        GROUP, CONFIG, OPTIONS, INPUTS, OUTPUTS
    ) = (
        'group', 'config', 'options', 'inputs', 'outputs'
    )

    IO_PROPERTIES = (
        NAME, DESCRIPTION, TYPE, DEFAULT, ERROR_OUTPUT
    ) = (
        'name', 'description', 'type', 'default', 'error_output'
    )

    input_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the input.'),
            required=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the input.')
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of the value of the input.'),
            default='String',
            constraints=[constraints.AllowedValues((
                'String', 'Number', 'CommaDelimitedList', 'Json'))]
        ),
        DEFAULT: properties.Schema(
            properties.Schema.STRING,
            _('Default value for the input if none is specified.'),
        ),
    }

    output_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the output.'),
            required=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the output.')
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of the value of the output.'),
            default='String',
            constraints=[constraints.AllowedValues((
                'String', 'Number', 'CommaDelimitedList', 'Json'))]
        ),
        ERROR_OUTPUT: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Denotes that the deployment is in an error state if this '
              'output has a value.'),
            default=False
        )
    }

    properties_schema = {
        GROUP: properties.Schema(
            properties.Schema.STRING,
            _('Namespace to group this software config by when delivered to '
              'a server. This may imply what configuration tool is going to '
              'perform the configuration.'),
            default='Heat::Ungrouped',
            required=True
        ),
        CONFIG: properties.Schema(
            properties.Schema.STRING,
            _('Configuration script or manifest which specifies what actual '
              'configuration is performed.'),
        ),
        OPTIONS: properties.Schema(
            properties.Schema.MAP,
            _('Map containing options specific to the configuration '
              'management tool used by this.'),
        ),
        INPUTS: properties.Schema(
            properties.Schema.LIST,
            _('Schema representing the inputs that this software config is '
              'expecting.'),
            schema=properties.Schema(properties.Schema.MAP,
                                     schema=input_schema)
        ),
        OUTPUTS: properties.Schema(
            properties.Schema.LIST,
            _('Schema representing the outputs that this software config '
              'will produce.'),
            schema=properties.Schema(properties.Schema.MAP,
                                     schema=output_schema)
        ),
    }

    attributes_schema = {
        "config": _("The config value of the software config.")
    }

    def handle_create(self):
        props = dict(self.properties)
        props[self.NAME] = self.physical_resource_name()

        sc = self.heat().software_configs.create(**props)
        self.resource_id_set(sc.id)

    def handle_delete(self):

        if self.resource_id is None:
            return

        try:
            self.heat().software_configs.delete(self.resource_id)
        except heat_exp.HTTPNotFound:
            logger.debug(
                _('Software config %s is not found.') % self.resource_id)

    def _resolve_attribute(self, name):
        '''
        "config" returns the config value of the software config. If the
         software config does not exist, returns an empty string.
        '''
        if name == self.CONFIG and self.resource_id:
            try:
                return self.get_software_config(self.heat(), self.resource_id)
            except exception.SoftwareConfigMissing:
                return ''

    @staticmethod
    def get_software_config(heat_client, software_config_id):
        '''
        Get the software config specified by :software_config_id:

        :param heat_client: the heat client to use
        :param software_config_id: the ID of the config to look for
        :returns: the config script string for :software_config_id:
        :raises: exception.NotFound
        '''
        try:
            return heat_client.software_configs.get(software_config_id).config
        except heat_exp.HTTPNotFound:
            raise exception.SoftwareConfigMissing(
                software_config_id=software_config_id)


def resource_mapping():
    return {
        'OS::Heat::SoftwareConfig': SoftwareConfig,
    }
