# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from heat.engine import constraints as constr
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.software_config import software_config as sc


class SoftwareComponent(sc.SoftwareConfig):
    '''
    A resource for describing and storing a software component.

    This resource is similar to OS::Heat::SoftwareConfig. In contrast to
    SoftwareConfig which allows for storing only one configuration (e.g. one
    script), SoftwareComponent allows for storing multiple configurations to
    address handling of all lifecycle hooks (CREATE, UPDATE, SUSPEND, RESUME,
    DELETE) for a software component in one place.

    This resource is backed by the persistence layer and the API of the
    SoftwareConfig resource, and only adds handling for the additional
    'configs' property and attribute.
    '''

    PROPERTIES = (
        CONFIGS, INPUTS, OUTPUTS, OPTIONS,
    ) = (
        'configs', 'inputs', 'outputs', 'options'
    )

    CONFIG_PROPERTIES = (
        CONFIG_ACTIONS, CONFIG_CONFIG, CONFIG_TOOL,
    ) = (
        'actions', 'config', 'tool',
    )

    ATTRIBUTES = (
        CONFIGS_ATTR,
    ) = (
        'configs',
    )

    # properties schema for one entry in the 'configs' list
    config_schema = properties.Schema(
        properties.Schema.MAP,
        schema={
            CONFIG_ACTIONS: properties.Schema(
                # Note: This properties schema allows for custom actions to be
                # specified, which will however require special handling in
                # in-instance hooks. By default, only the standard actions
                # stated below will be handled.
                properties.Schema.LIST,
                _('Lifecycle actions to which the configuration applies. '
                  'The string values provided for this property can include '
                  'the standard resource actions CREATE, DELETE, UPDATE, '
                  'SUSPEND and RESUME supported by Heat.'),
                default=[resource.Resource.CREATE, resource.Resource.UPDATE],
                schema=properties.Schema(properties.Schema.STRING),
                constraints=[
                    constr.Length(min=1),
                ],
                required=True
            ),
            CONFIG_CONFIG: sc.SoftwareConfig.properties_schema[
                sc.SoftwareConfig.CONFIG
            ],
            CONFIG_TOOL: properties.Schema(
                properties.Schema.STRING,
                _('The configuration tool used to actually apply the '
                  'configuration on a server. This string property has '
                  'to be understood by in-instance tools running inside '
                  'deployed servers.'),
                required=True
            )
        }
    )

    properties_schema = {
        CONFIGS: properties.Schema(
            properties.Schema.LIST,
            _('The list of configurations for the different lifecycle actions '
              'of the represented software component.'),
            schema=config_schema,
            constraints=[constr.Length(min=1)],
            required=True
        ),
        INPUTS: sc.SoftwareConfig.properties_schema[
            sc.SoftwareConfig.INPUTS],
        OUTPUTS: sc.SoftwareConfig.properties_schema[
            sc.SoftwareConfig.OUTPUTS],
        OPTIONS: sc.SoftwareConfig.properties_schema[
            sc.SoftwareConfig.OPTIONS],
    }

    def handle_create(self):
        props = dict(self.properties)
        props[self.NAME] = self.physical_resource_name()
        # use config property of SoftwareConfig to store configs list
        configs = self.properties.get(self.CONFIGS)
        props[self.CONFIG] = {self.CONFIGS: configs}
        # set 'group' to enable component processing by in-instance hook
        props[self.GROUP] = 'component'

        sc = self.heat().software_configs.create(**props)
        self.resource_id_set(sc.id)

    def _resolve_attribute(self, name):
        '''
        Retrieve attributes of the SoftwareComponent resource.

        'configs' returns the list of configurations for the software
        component's lifecycle actions. If the attribute does not exist,
        an empty list is returned.
        '''
        if name == self.CONFIGS_ATTR and self.resource_id:
            try:
                config = self.heat().software_configs.get(self.resource_id).\
                    config
                # configs list is stored in 'config' property of parent class
                # (see handle_create)
                return config.get(self.CONFIGS)
            except Exception as ex:
                if self.client_plugin().is_not_found(ex):
                    return None

    def validate(self):
        '''Validate SoftwareComponent properties consistency.'''
        super(SoftwareComponent, self).validate()

        # One lifecycle action (e.g. CREATE) can only be associated with one
        # config; otherwise a way to define ordering would be required.
        configs = self.properties.get(self.CONFIGS, [])
        config_actions = set()
        for config in configs:
            actions = config.get(self.CONFIG_ACTIONS)
            if any(action in config_actions for action in actions):
                msg = _('Defining more than one configuration for the same '
                        'action in SoftwareComponent "%s" is not allowed.')\
                    % self.name
                raise exception.StackValidationFailed(message=msg)
            config_actions.update(actions)


def resource_mapping():
    return {
        'OS::Heat::SoftwareComponent': SoftwareComponent,
    }
