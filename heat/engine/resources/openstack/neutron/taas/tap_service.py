#    Copyright (c) 2018 AT&T Corporation.
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
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation


class TapService(neutron.NeutronResource):
    """A resource for neutron tap-as-a-service tap-service.

    This plug-in requires neutron-taas. So to enable this
    plug-in, install this library and restart the heat-engine.

    A Tap-Service represents the port on which the mirrored traffic is
    delivered. Any VM that uses the mirrored data is attached to this port.
    """

    required_service_extension = 'taas'

    entity = 'tap_service'

    support_status = support.SupportStatus(version='12.0.0')

    PROPERTIES = (
        NAME, DESCRIPTION, PORT,
        ) = (
        'name', 'description', 'port',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the Tap-Service.'),
            default="",
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the Tap-Service.'),
            default="",
            update_allowed=True
        ),
        PORT: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the tap-service neutron port.'),
            constraints=[constraints.CustomConstraint('neutron.port')],
            required=True,
        ),
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.PORT],
                client_plugin=self.client_plugin(),
                finder='find_resourceid_by_name_or_id',
                entity='port'
            )
        ]

    def _show_resource(self):
        return self.client_plugin().show_ext_resource('tap_service',
                                                      self.resource_id)

    def handle_create(self):
        props = self.prepare_properties(self.properties,
                                        self.physical_resource_name())
        props['port_id'] = props.pop(self.PORT)
        ts = self.client_plugin().create_ext_resource('tap_service',
                                                      props)
        self.resource_id_set(ts['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client_plugin().update_ext_resource('tap_service',
                                                     prop_diff,
                                                     self.resource_id)

    def handle_delete(self):
        if self.resource_id is None:
            return
        with self.client_plugin().ignore_not_found:
                self.client_plugin().delete_ext_resource('tap_service',
                                                         self.resource_id)

    def check_create_complete(self, data):
        return self.client_plugin().check_ext_resource_status(
            'tap_service', self.resource_id)

    def check_update_complete(self, prop_diff):
        if prop_diff:
            return self.client_plugin().check_ext_resource_status(
                'tap_service', self.resource_id)
        return True

    def check_delete_complete(self, data):
        if self.resource_id is None:
            return True

        with self.client_plugin().ignore_not_found:
            try:
                if self.client_plugin().check_ext_resource_status(
                        'tap_service', self.resource_id):
                    self.client_plugin().delete_ext_resource(
                        'tap_service', self.resource_id)
            except exception.ResourceInError:
                # Still try to delete tap resource in error state
                self.client_plugin().delete_ext_resource('tap_service',
                                                         self.resource_id)
            return False

        return True


def resource_mapping():
    return {
        'OS::Neutron::TaaS::TapService': TapService,
    }
