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
from heat.common import template_format
from heat.engine import properties
from heat.engine.resources.openstack.heat import software_config
from heat.engine import support
from heat.rpc import api as rpc_api


class CloudConfig(software_config.SoftwareConfig):
    """A configuration resource for representing cloud-init cloud-config.

    This resource allows cloud-config YAML to be defined and stored by the
    config API. Any intrinsic functions called in the config will be resolved
    before storing the result.

    This resource will generally be referenced by OS::Nova::Server user_data,
    or OS::Heat::MultipartMime parts config. Since cloud-config is boot-only
    configuration, any changes to the definition will result in the
    replacement of all servers which reference it.
    """

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        CLOUD_CONFIG
    ) = (
        'cloud_config'
    )

    properties_schema = {
        CLOUD_CONFIG: properties.Schema(
            properties.Schema.MAP,
            _('Map representing the cloud-config data structure which will '
              'be formatted as YAML.')
        )
    }

    def handle_create(self):
        cloud_config = template_format.yaml.dump(
            self.properties[self.CLOUD_CONFIG],
            Dumper=template_format.yaml_dumper)
        props = {
            rpc_api.SOFTWARE_CONFIG_NAME: self.physical_resource_name(),
            rpc_api.SOFTWARE_CONFIG_CONFIG: '#cloud-config\n%s' % cloud_config,
            rpc_api.SOFTWARE_CONFIG_GROUP: 'Heat::Ungrouped'
        }
        sc = self.rpc_client().create_software_config(self.context, **props)
        self.resource_id_set(sc[rpc_api.SOFTWARE_CONFIG_ID])


def resource_mapping():
    return {
        'OS::Heat::CloudConfig': CloudConfig,
    }
