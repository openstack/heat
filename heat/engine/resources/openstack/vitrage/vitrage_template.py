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

from oslo_log import log as logging

from heat.common import exception
from heat.common.i18n import _
from heat.engine import properties
from heat.engine import resource
from heat.engine import support

LOG = logging.getLogger(__name__)


class VitrageTemplate(resource.Resource):
    """A resource for managing Vitrage templates.

    A Vitrage template defines conditions and actions, based on the Vitrage
    topology graph. For example, if there is an "instance down" alarm on an
    instance, then execute a Mistral healing workflow.

    The VitrageTemplate resource generates and adds to Vitrage a template based
    on the input parameters.
    """

    default_client_name = "vitrage"

    support_status = support.SupportStatus(version='16.0.0')

    TEMPLATE_NAME = 'template_name'

    PROPERTIES = (
        TEMPLATE_FILE, TEMPLATE_PARAMS
    ) = (
        'template_file', 'template_params'
    )

    properties_schema = {
        TEMPLATE_FILE: properties.Schema(
            properties.Schema.STRING,
            _("Path of the Vitrage template to use."),
            required=True,
        ),
        TEMPLATE_PARAMS: properties.Schema(
            properties.Schema.MAP,
            _("Input parameters for the Vitrage template."),
            required=True,
        ),
    }

    def handle_create(self):
        """Create a Vitrage template."""

        # Add the new template to Vitrage
        params = self.properties[self.TEMPLATE_PARAMS]
        params[self.TEMPLATE_NAME] = self.physical_resource_name()
        params['description'] = self.properties.get('description')

        LOG.debug('Vitrage params for template add: %s', params)

        added_templates = self.client().template.add(
            template_str=self.properties[self.TEMPLATE_FILE], params=params)

        if added_templates and len(added_templates) > 0:
            if added_templates[0].get('status') == 'LOADING':
                self.resource_id_set(added_templates[0].get('uuid'))
                LOG.debug('Added Vitrage template: %s',
                          str(added_templates[0].get('uuid')))
            else:
                LOG.warning("Failed to add template to Vitrage: %s",
                            added_templates[0].get('status details'))
        else:
            LOG.warning("Failed to add template to Vitrage")

    def handle_delete(self):
        """Delete the Vitrage template."""
        if not self.resource_id:
            return
        LOG.debug('Deleting Vitrage template %s', self.resource_id)
        self.client().template.delete(self.resource_id)

    def validate(self):
        """Validate a Vitrage template."""
        super(VitrageTemplate, self).validate()

        try:
            params = self.properties[self.TEMPLATE_PARAMS]
            params[self.TEMPLATE_NAME] = self.physical_resource_name()
            params['description'] = self.properties.get('description')

            for key, value in params.items():
                if value is None:
                    # some values depend on creation of other objects, which
                    # was not done yet. Use temporary values for now.
                    params[key] = 'temp'

            LOG.debug('Vitrage params for template validate: %s', params)

            validation = self.client().template.validate(
                template_str=self.properties[self.TEMPLATE_FILE],
                params=params)

        except Exception as e:
            msg = _("Exception when calling Vitrage template validate: %s") % \
                e.message
            raise exception.StackValidationFailed(message=msg)

        if not validation or not validation.get('results') or \
                len(validation['results']) != 1 or \
                'status code' not in validation['results'][0]:
            msg = _("Failed to validate Vitrage template %s") % \
                self.TEMPLATE_FILE
            raise exception.StackValidationFailed(message=msg)

        result = validation['results'][0]
        if result['status code'] != 0:
            msg = _("Failed to validate Vitrage template. Error: %s") % \
                result.get('message')
            raise exception.StackValidationFailed(message=msg)


def resource_mapping():
    return {
        'OS::Vitrage::Template': VitrageTemplate,
    }
