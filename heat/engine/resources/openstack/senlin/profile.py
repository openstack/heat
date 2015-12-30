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
#
#    Copyright 2015 IBM Corp.

from heat.common import exception
from heat.common.i18n import _
from heat.common import template_format
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class Profile(resource.Resource):
    """A resource that creates a Senlin Profile.

    Profile resource in senlin is a template describing how to create nodes in
    cluster.
    """

    support_status = support.SupportStatus(version='6.0.0')

    default_client_name = 'senlin'

    PROPERTIES = (
        NAME, SPEC, METADATA,
    ) = (
        'name', 'spec', 'metadata',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the senlin profile. By default, physical resource name '
              'is used.'),
            update_allowed=True,
        ),
        SPEC: properties.Schema(
            properties.Schema.STRING,
            _('The spec template content for Senlin profile, should be '
              'either in YAML or JSON format.'),
            required=True
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Metadata key-values defined for profile.'),
            update_allowed=True,
        )
    }

    def __init__(self, name, definition, stack):
        super(Profile, self).__init__(name, definition, stack)
        self._spec = None

    def _parse_spec(self, spec):
        if self._spec is None:
            self._spec = template_format.simple_parse(spec)
        return self._spec

    def handle_create(self):
        params = {
            'name': (self.properties[self.NAME] or
                     self.physical_resource_name()),
            'spec': self._parse_spec(self.properties[self.SPEC]),
            'metadata': self.properties[self.METADATA],
        }

        profile = self.client().create_profile(**params)
        self.resource_id_set(profile.id)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client().delete_profile(self.resource_id)

    def validate(self):
        try:
            self._parse_spec(self.properties[self.SPEC])
        except ValueError as ex:
            msg = _("Failed to parse %(spec)s: %(ex)s") % {
                'spec': self.SPEC,
                'ex': ex
            }
            raise exception.StackValidationFailed(message=msg)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().update_profile(self.resource_id, **prop_diff)

    def _show_resource(self):
        profile = self.client().get_profile(self.resource_id)
        return profile.to_dict()


def resource_mapping():
    return {
        'OS::Senlin::Profile': Profile
    }
