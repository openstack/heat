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

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.keystone import role_assignments
from heat.engine import support


class KeystoneUser(resource.Resource,
                   role_assignments.KeystoneRoleAssignmentMixin):
    """Heat Template Resource for Keystone User."""

    support_status = support.SupportStatus(
        version='2015.1',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    entity = 'users'

    PROPERTIES = (
        NAME, DOMAIN, DESCRIPTION, ENABLED, EMAIL, PASSWORD,
        DEFAULT_PROJECT, GROUPS
    ) = (
        'name', 'domain', 'description', 'enabled', 'email', 'password',
        'default_project', 'groups'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of keystone user.'),
            update_allowed=True
        ),
        DOMAIN: properties.Schema(
            properties.Schema.STRING,
            _('Name of keystone domain.'),
            default='default',
            update_allowed=True,
            constraints=[constraints.CustomConstraint('keystone.domain')]
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of keystone user.'),
            default='',
            update_allowed=True
        ),
        ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Keystone user is enabled or disabled'),
            default=True,
            update_allowed=True
        ),
        EMAIL: properties.Schema(
            properties.Schema.STRING,
            _('Email address of keystone user.'),
            update_allowed=True
        ),
        PASSWORD: properties.Schema(
            properties.Schema.STRING,
            _('Password of keystone user.'),
            update_allowed=True
        ),
        DEFAULT_PROJECT: properties.Schema(
            properties.Schema.STRING,
            _('Default project of keystone user.'),
            update_allowed=True,
            constraints=[constraints.CustomConstraint('keystone.project')]
        ),
        GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('keystone user groups.'),
            update_allowed=True,
            schema=properties.Schema(
                properties.Schema.STRING,
                _('keystone user group.'),
                constraints=[constraints.CustomConstraint('keystone.group')]
            )
        )
    }

    properties_schema.update(
        role_assignments.KeystoneRoleAssignmentMixin.mixin_properties_schema)

    def validate(self):
        super(KeystoneUser, self).validate()
        self.validate_assignment_properties()

    def client(self):
        return super(KeystoneUser, self).client().client

    def _create_user(self,
                     user_name,
                     description,
                     domain,
                     default_project,
                     enabled=None,
                     email=None,
                     password=None):
        domain = (self.client_plugin().get_domain_id(domain))
        if default_project:
            default_project = (self.client_plugin().
                               get_project_id(default_project))

        return self.client().users.create(
            name=user_name,
            domain=domain,
            description=description,
            enabled=enabled,
            email=email,
            password=password,
            default_project=default_project)

    def _delete_user(self, user_id):
        return self.client().users.delete(user_id)

    def _update_user(self,
                     user_id,
                     domain,
                     new_name=None,
                     new_description=None,
                     new_email=None,
                     new_password=None,
                     new_default_project=None,
                     enabled=None):
        values = dict()

        if new_name is not None:
            values['name'] = new_name
        if new_description is not None:
            values['description'] = new_description
        if new_email is not None:
            values['email'] = new_email
        if new_password is not None:
            values['password'] = new_password
        if new_default_project is not None:
            values['default_project'] = new_default_project
        if enabled is not None:
            values['enabled'] = enabled

        values['user'] = user_id
        domain = (self.client_plugin().get_domain_id(domain))

        values['domain'] = domain

        return self.client().users.update(**values)

    def _add_user_to_groups(self, user_id, groups):
        if groups is not None:
            group_ids = [self.client_plugin().get_group_id(group)
                         for group in groups]

            for group_id in group_ids:
                self.client().users.add_to_group(user_id,
                                                 group_id)

    def _remove_user_from_groups(self, user_id, groups):
        if groups is not None:
            group_ids = [self.client_plugin().get_group_id(group)
                         for group in groups]

            for group_id in group_ids:
                self.client().users.remove_from_group(user_id,
                                                      group_id)

    def _find_diff(self, updated_prps, stored_prps):
        new_group_ids = [self.client_plugin().get_group_id(group)
                         for group in
                         (set(updated_prps or []) -
                          set(stored_prps or []))]

        removed_group_ids = [self.client_plugin().get_group_id(group)
                             for group in
                             (set(stored_prps or []) -
                              set(updated_prps or []))]

        return new_group_ids, removed_group_ids

    def handle_create(self):
        user_name = (self.properties.get(self.NAME) or
                     self.physical_resource_name())
        description = self.properties.get(self.DESCRIPTION)
        domain = self.properties.get(self.DOMAIN)
        enabled = self.properties.get(self.ENABLED)
        email = self.properties.get(self.EMAIL)
        password = self.properties.get(self.PASSWORD)
        default_project = self.properties.get(self.DEFAULT_PROJECT)
        groups = self.properties.get(self.GROUPS)

        user = self._create_user(
            user_name=user_name,
            description=description,
            domain=domain,
            enabled=enabled,
            email=email,
            password=password,
            default_project=default_project
        )

        self.resource_id_set(user.id)

        self._add_user_to_groups(user.id, groups)

        self.create_assignment(user_id=user.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            name = None
            # Don't update the name if no change
            if self.NAME in prop_diff:
                name = prop_diff[self.NAME] or self.physical_resource_name()

            description = prop_diff.get(self.DESCRIPTION)
            enabled = prop_diff.get(self.ENABLED)
            email = prop_diff.get(self.EMAIL)
            password = prop_diff.get(self.PASSWORD)
            domain = (prop_diff.get(self.DOMAIN) or
                      self._stored_properties_data.get(self.DOMAIN))

            default_project = prop_diff.get(self.DEFAULT_PROJECT)

            self._update_user(
                user_id=self.resource_id,
                domain=domain,
                new_name=name,
                new_description=description,
                enabled=enabled,
                new_default_project=default_project,
                new_email=email,
                new_password=password
            )

            if self.GROUPS in prop_diff:
                (new_group_ids, removed_group_ids) = self._find_diff(
                    prop_diff[self.GROUPS],
                    self._stored_properties_data.get(self.GROUPS))
                if new_group_ids:
                    self._add_user_to_groups(self.resource_id, new_group_ids)

                if removed_group_ids:
                    self._remove_user_from_groups(self.resource_id,
                                                  removed_group_ids)

        self.update_assignment(prop_diff=prop_diff, user_id=self.resource_id)

    def handle_delete(self):
        if self.resource_id is not None:
            try:
                self.delete_assignment(user_id=self.resource_id)

                if self._stored_properties_data.get(self.GROUPS) is not None:
                    self._remove_user_from_groups(
                        self.resource_id,
                        [self.client_plugin().get_group_id(group)
                         for group in
                         self._stored_properties_data.get(self.GROUPS)])

                self._delete_user(user_id=self.resource_id)
            except Exception as ex:
                self.client_plugin().ignore_not_found(ex)


def resource_mapping():
    return {
        'OS::Keystone::User': KeystoneUser
    }
