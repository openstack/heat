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
from heat.engine import resource
from heat.engine import support


class CinderVolumeType(resource.Resource):
    """A resource for creating cinder volume types.

    Note that default cinder security policy usage of this resource
    is limited to being used by administrators only.
    """

    support_status = support.SupportStatus(version='2015.1')

    default_client_name = 'cinder'

    entity = 'volume_types'

    PROPERTIES = (
        NAME, METADATA, IS_PUBLIC, DESCRIPTION, PROJECTS,
    ) = (
        'name', 'metadata', 'is_public', 'description', 'projects',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the volume type.'),
            required=True,
            update_allowed=True,
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('The extra specs key and value pairs of the volume type.'),
            update_allowed=True
        ),
        IS_PUBLIC: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether the volume type is accessible to the public.'),
            default=True,
            support_status=support.SupportStatus(version='5.0.0'),
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the volume type.'),
            update_allowed=True,
            support_status=support.SupportStatus(version='5.0.0'),
        ),
        PROJECTS: properties.Schema(
            properties.Schema.LIST,
            _('Projects to add volume type access to. NOTE: This '
              'property is only supported since Cinder API V2.'),
            support_status=support.SupportStatus(version='5.0.0'),
            update_allowed=True,
            schema=properties.Schema(
                properties.Schema.STRING,
                constraints=[
                    constraints.CustomConstraint('keystone.project')
                ],
            ),
            default=[],
        ),
    }

    def _add_projects_access(self, projects):
        for project in projects:
            project_id = self.keystone().get_project_id(project)
            self.cinder().volume_type_access.add_project_access(
                self.resource_id, project_id)

    def handle_create(self):
        args = {
            'name': self.properties[self.NAME],
            'is_public': self.properties[self.IS_PUBLIC],
            'description': self.properties[self.DESCRIPTION]
        }

        volume_type = self.client().volume_types.create(**args)
        self.resource_id_set(volume_type.id)
        vtype_metadata = self.properties[self.METADATA]
        if vtype_metadata:
            volume_type.set_keys(vtype_metadata)
        self._add_projects_access(self.properties[self.PROJECTS])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Update the name, description and metadata for volume type."""

        update_args = {}
        # Update the name, description of cinder volume type
        if self.DESCRIPTION in prop_diff:
            update_args['description'] = prop_diff.get(self.DESCRIPTION)
        if self.NAME in prop_diff:
            update_args['name'] = prop_diff.get(self.NAME)
        if update_args:
            self.client().volume_types.update(self.resource_id, **update_args)
        # Update the key-value pairs of cinder volume type.
        if self.METADATA in prop_diff:
            volume_type = self.client().volume_types.get(self.resource_id)
            old_keys = volume_type.get_keys()
            volume_type.unset_keys(old_keys)
            new_keys = prop_diff.get(self.METADATA)
            if new_keys is not None:
                volume_type.set_keys(new_keys)
        # Update the projects access for volume type
        if self.PROJECTS in prop_diff:
            old_access_list = self.cinder().volume_type_access.list(
                self.resource_id)['volume_type_access']
            old_projects = [ac['project_id'] for ac in old_access_list]
            new_projects = prop_diff.get(self.PROJECTS)
            # first remove the old projects access
            for project_id in (set(old_projects) - set(new_projects)):
                self.cinder().volume_type_access.remove_project_access(
                    self.resource_id, project_id)
            # add the new projects access
            self._add_projects_access(set(new_projects) - set(old_projects))

    # TODO(huangtianhua): remove this method when bug #1479641 is fixed.
    def _show_resource(self):
        vtype = self.client().volume_types.get(self.resource_id)
        return vtype._info

    def validate(self):
        super(CinderVolumeType, self).validate()

        if self.properties[self.PROJECTS]:
            if self.cinder().volume_api_version == 1:
                raise exception.NotSupported(
                    feature=_('Using Cinder API V1, volume type access'))
            if self.properties[self.IS_PUBLIC]:
                msg = (_('Can not specify property "%s" '
                         'if the volume type is public.') % self.PROJECTS)
                raise exception.StackValidationFailed(message=msg)


def resource_mapping():
    return {
        'OS::Cinder::VolumeType': CinderVolumeType
    }
