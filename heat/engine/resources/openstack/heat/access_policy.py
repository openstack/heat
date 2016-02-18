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
from heat.engine import properties
from heat.engine import resource


class AccessPolicy(resource.Resource):
    """Resource for defining which resources can be accessed by users.

    NOTE: Now this resource is actually associated with an AWS user resource,
    not any OS:: resource though it is registered under the OS namespace below.

    Resource for defining resources that users are allowed to access by the
    DescribeStackResource API.
    """
    PROPERTIES = (
        ALLOWED_RESOURCES,
    ) = (
        'AllowedResources',
    )

    properties_schema = {
        ALLOWED_RESOURCES: properties.Schema(
            properties.Schema.LIST,
            _('Resources that users are allowed to access by the '
              'DescribeStackResource API.'),
            required=True
        ),
    }

    def handle_create(self):
        pass

    def validate(self):
        """Make sure all the AllowedResources are present."""
        super(AccessPolicy, self).validate()

        resources = self.properties[self.ALLOWED_RESOURCES]
        # All of the provided resource names must exist in this stack
        for res in resources:
            if res not in self.stack:
                msg = _("AccessPolicy resource %s not in stack") % res
                raise exception.StackValidationFailed(message=msg)

    def access_allowed(self, resource_name):
        return resource_name in self.properties[self.ALLOWED_RESOURCES]


def resource_mapping():
    return {
        'OS::Heat::AccessPolicy': AccessPolicy,
    }
