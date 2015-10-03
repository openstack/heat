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


class DataSource(resource.Resource):
    """A resource for creating sahara data source.

    A data source stores an URL which designates the location of input
    or output data and any credentials needed to access the location.
    """

    support_status = support.SupportStatus(version='5.0.0')

    PROPERTIES = (
        NAME, TYPE, URL, DESCRIPTION, CREDENTIALS

    ) = (
        'name', 'type', 'url', 'description', 'credentials'
    )

    _CREDENTIAL_KEYS = (
        USER, PASSWORD
    ) = (
        'user', 'password'
    )

    _DATA_SOURCE_TYPES = (
        SWIFT, HDFS, MAPRFS, MANILA
    ) = (
        'swift', 'hdfs', 'maprfs', 'manila'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _("Name of the data source."),
            update_allowed=True
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of the data source.'),
            constraints=[
                constraints.AllowedValues(_DATA_SOURCE_TYPES),
            ],
            required=True,
            update_allowed=True
        ),
        URL: properties.Schema(
            properties.Schema.STRING,
            _('URL for the data source.'),
            required=True,
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the data source.'),
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
                    _('Username for accessing the data source URL.'),
                    required=True
                ),
                PASSWORD: properties.Schema(
                    properties.Schema.STRING,
                    _("Password for accessing the data source URL."),
                    required=True
                )
            },
            update_allowed=True
        )
    }

    default_client_name = 'sahara'

    entity = 'data_sources'

    def _data_source_name(self):
        return self.properties[self.NAME] or self.physical_resource_name()

    def handle_create(self):
        credentials = self.properties[self.CREDENTIALS] or {}
        args = {
            'name': self._data_source_name(),
            'description': self.properties[self.DESCRIPTION],
            'data_source_type': self.properties[self.TYPE],
            'url': self.properties[self.URL],
            'credential_user': credentials.get(self.USER),
            'credential_pass': credentials.get(self.PASSWORD)
        }

        data_source = self.client().data_sources.create(**args)
        self.resource_id_set(data_source.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.properties = json_snippet.properties(
                self.properties_schema,
                self.context)
            data = dict(self.properties)
            if not data.get(self.NAME):
                data[self.NAME] = self.physical_resource_name()
            self.client().data_sources.update(self.resource_id, data)


def resource_mapping():
    return {
        'OS::Sahara::DataSource': DataSource
    }
