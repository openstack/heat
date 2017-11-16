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

from oslo_utils import uuidutils

from heat.common import exception
from heat.common.i18n import _
from heat.engine import properties
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import support


class JobBinary(resource.Resource):
    """A resource for creating sahara job binary.

    A job binary stores an URL to a single script or Jar file and any
    credentials needed to retrieve the file.
    """

    support_status = support.SupportStatus(version='5.0.0')

    PROPERTIES = (
        NAME, URL, DESCRIPTION, CREDENTIALS
    ) = (
        'name', 'url', 'description', 'credentials'
    )

    _CREDENTIAL_KEYS = (
        USER, PASSWORD
    ) = (
        'user', 'password'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the job binary.'),
            update_allowed=True
        ),
        URL: properties.Schema(
            properties.Schema.STRING,
            _('URL for the job binary. Must be in the format '
              'swift://<container>/<path> or internal-db://<uuid>.'),
            required=True,
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the job binary.'),
            default='',
            update_allowed=True
        ),
        CREDENTIALS: properties.Schema(
            properties.Schema.MAP,
            _('Credentials used for swift. Not required if sahara is '
              'configured to use proxy users and delegated trusts for '
              'access.'),
            schema={
                USER: properties.Schema(
                    properties.Schema.STRING,
                    _('Username for accessing the job binary URL.'),
                    required=True
                ),
                PASSWORD: properties.Schema(
                    properties.Schema.STRING,
                    _('Password for accessing the job binary URL.'),
                    required=True
                ),
            },
            update_allowed=True
        )
    }

    default_client_name = 'sahara'

    entity = 'job_binaries'

    def _job_binary_name(self):
        return self.properties[self.NAME] or self.physical_resource_name()

    def _prepare_properties(self):
        credentials = self.properties[self.CREDENTIALS] or {}
        return {
            'name': self._job_binary_name(),
            'description': self.properties[self.DESCRIPTION],
            'url': self.properties[self.URL],
            'extra': credentials
        }

    def validate(self):
        super(JobBinary, self).validate()
        url = self.properties[self.URL]
        if not (url.startswith('swift://') or (url.startswith('internal-db://')
                and uuidutils.is_uuid_like(url[len("internal-db://"):]))):
            msg = _("%s is not a valid job location.") % url
            raise exception.StackValidationFailed(
                path=[self.stack.t.RESOURCES, self.name,
                      self.stack.t.get_section_name(rsrc_defn.PROPERTIES)],
                message=msg)

    def handle_create(self):
        args = self._prepare_properties()
        job_binary = self.client().job_binaries.create(**args)
        self.resource_id_set(job_binary.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.properties = json_snippet.properties(
                self.properties_schema,
                self.context)
            data = self._prepare_properties()
            self.client().job_binaries.update(self.resource_id, data)


def resource_mapping():
    return {
        'OS::Sahara::JobBinary': JobBinary
    }
