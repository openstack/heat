#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import translation


class SaharaImageRegistry(resource.Resource):
    """A resource for registering an image in sahara.

    Allows to register an image in the sahara image registry and add tags.
    """

    support_status = support.SupportStatus(version='6.0.0')

    PROPERTIES = (
        IMAGE, USERNAME, DESCRIPTION, TAGS

    ) = (
        'image', 'username', 'description', 'tags'
    )

    properties_schema = {
        IMAGE: properties.Schema(
            properties.Schema.STRING,
            _("ID or name of the image to register."),
            constraints=[
                constraints.CustomConstraint('glance.image')
            ],
            required=True
        ),
        USERNAME: properties.Schema(
            properties.Schema.STRING,
            _('Username of privileged user in the image.'),
            required=True,
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the image.'),
            default='',
            update_allowed=True
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('Tags to add to the image.'),
            schema=properties.Schema(
                properties.Schema.STRING
            ),
            update_allowed=True,
            default=[]
        )
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.IMAGE],
                client_plugin=self.client_plugin('glance'),
                finder='find_image_by_name_or_id')
        ]

    default_client_name = 'sahara'

    entity = 'images'

    def handle_create(self):
        self.resource_id_set(self.properties[self.IMAGE])
        self.client().images.update_image(
            self.resource_id,
            self.properties[self.USERNAME],
            self.properties[self.DESCRIPTION]
        )
        if self.properties[self.TAGS]:
            self.client().images.update_tags(self.resource_id,
                                             self.properties[self.TAGS])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.properties = json_snippet.properties(
                self.properties_schema,
                self.context)
            if self.USERNAME in prop_diff or self.DESCRIPTION in prop_diff:
                self.client().images.update_image(
                    self.resource_id,
                    self.properties[self.USERNAME],
                    self.properties[self.DESCRIPTION]
                )
            if self.TAGS in prop_diff:
                self.client().images.update_tags(self.resource_id,
                                                 self.properties[self.TAGS])

    def handle_delete(self):
        if self.resource_id is None:
            return

        with self.client_plugin().ignore_not_found:
            self.client().images.unregister_image(self.resource_id)


def resource_mapping():
    return {
        'OS::Sahara::ImageRegistry': SaharaImageRegistry
    }
