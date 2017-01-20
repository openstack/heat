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

    Volume type resource allows to define, whether volume, which will be use
    this type, will public and which projects are allowed to work with it.
    Also, there can be some user-defined metadata.

    Note that default cinder security policy usage of this resource
    is limited to being used by administrators only.
    """

    support_status = support.SupportStatus(version='2015.1')

    default_client_name = 'cinder'

    entity = 'volume_types'

    required_service_extension = 'os-types-manage'

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
            update_allowed=True
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
            project_id = self.client_plugin('keystone').get_project_id(project)
            self.client().volume_type_access.add_project_access(
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
        # Update the name, description, is_public of cinder volume type
        is_public = self.properties[self.IS_PUBLIC]
        if self.DESCRIPTION in prop_diff:
            update_args['description'] = prop_diff.get(self.DESCRIPTION)
        if self.NAME in prop_diff:
            update_args['name'] = prop_diff.get(self.NAME)
        if self.IS_PUBLIC in prop_diff:
            is_public = prop_diff.get(self.IS_PUBLIC)
            update_args['is_public'] = is_public
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
        if self.PROJECTS in prop_diff and not is_public:
            old_access_list = self.client().volume_type_access.list(
                self.resource_id)
            old_projects = [ac.to_dict()['project_id'] for
                            ac in old_access_list]
            new_projects = prop_diff.get(self.PROJECTS)
            # first remove the old projects access
            for project_id in (set(old_projects) - set(new_projects)):
                self.client().volume_type_access.remove_project_access(
                    self.resource_id, project_id)
            # add the new projects access
            self._add_projects_access(set(new_projects) - set(old_projects))

    def validate(self):
        super(CinderVolumeType, self).validate()

        if self.properties[self.PROJECTS]:
            if self.properties[self.IS_PUBLIC]:
                msg = (_('Can not specify property "%s" '
                         'if the volume type is public.') % self.PROJECTS)
                raise exception.StackValidationFailed(message=msg)

    def get_live_resource_data(self):
        try:
            resource_object = self.client().volume_types.get(self.resource_id)
            resource_data = resource_object.to_dict()
        except Exception as ex:
            if self.client_plugin().is_not_found(ex):
                raise exception.EntityNotFound(entity='Resource',
                                               name=self.name)
            raise
        return resource_object, resource_data

    def parse_live_resource_data(self, resource_properties, resource_data):
        resource_reality = {}
        resource_object, resource_data = resource_data

        resource_reality.update({
            self.NAME: resource_data.get(self.NAME),
            self.DESCRIPTION: resource_data.get(self.DESCRIPTION)
        })

        metadata = resource_object.get_keys()
        resource_reality.update({self.METADATA: metadata or {}})

        is_public = resource_data.get(self.IS_PUBLIC)
        resource_reality.update({self.IS_PUBLIC: is_public})
        projects = []
        if not is_public:
            accesses = self.client().volume_type_access.list(self.resource_id)
            for access in accesses:
                projects.append(access.to_dict().get('project_id'))
        resource_reality.update({self.PROJECTS: projects})

        return resource_reality


def resource_mapping():
    return {
        'OS::Cinder::VolumeType': CinderVolumeType
    }
