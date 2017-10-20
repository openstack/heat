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
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.keystone import role_assignments
from heat.engine import support
from heat.engine import translation


class KeystoneUser(resource.Resource,
                   role_assignments.KeystoneRoleAssignmentMixin):
    """Heat Template Resource for Keystone User.

    Users represent an individual API consumer. A user itself must be owned by
    a specific domain, and hence all user names are not globally unique, but
    only unique to their domain.
    """

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
            _('Name or ID of keystone domain.'),
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
            _('Keystone user is enabled or disabled.'),
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
            _('Name or ID of default project of keystone user.'),
            update_allowed=True,
            constraints=[constraints.CustomConstraint('keystone.project')]
        ),
        GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('Keystone user groups.'),
            update_allowed=True,
            schema=properties.Schema(
                properties.Schema.STRING,
                _('Keystone user group.'),
                constraints=[constraints.CustomConstraint('keystone.group')]
            )
        )
    }

    properties_schema.update(
        role_assignments.KeystoneRoleAssignmentMixin.mixin_properties_schema)

    ATTRIBUTES = (
        NAME_ATTR, DEFAULT_PROJECT_ATTR, DOMAIN_ATTR, ENABLED_ATTR,
        PASSWORD_EXPIRES_AT_ATTR
    ) = (
        'name', 'default_project_id', 'domain_id', 'enabled',
        'password_expires_at'
    )
    attributes_schema = {
        NAME_ATTR: attributes.Schema(
            _('User name.'),
            support_status=support.SupportStatus(version='9.0.0'),
            type=attributes.Schema.STRING
        ),
        DEFAULT_PROJECT_ATTR: attributes.Schema(
            _('Default project id for user.'),
            support_status=support.SupportStatus(version='9.0.0'),
            type=attributes.Schema.STRING
        ),
        DOMAIN_ATTR: attributes.Schema(
            _('Domain id for user.'),
            support_status=support.SupportStatus(version='9.0.0'),
            type=attributes.Schema.STRING
        ),
        ENABLED_ATTR: attributes.Schema(
            _('Flag of enable user.'),
            support_status=support.SupportStatus(version='9.0.0'),
            type=attributes.Schema.BOOLEAN
        ),
        PASSWORD_EXPIRES_AT_ATTR: attributes.Schema(
            _('Show user password expiration time.'),
            support_status=support.SupportStatus(version='9.0.0'),
            type=attributes.Schema.STRING
        ),
    }

    def translation_rules(self, properties):
        return [
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.DOMAIN],
                client_plugin=self.client_plugin(),
                finder='get_domain_id'
            ),
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.DEFAULT_PROJECT],
                client_plugin=self.client_plugin(),
                finder='get_project_id'
            ),
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.GROUPS],
                client_plugin=self.client_plugin(),
                finder='get_group_id'
            ),
        ]

    def validate(self):
        super(KeystoneUser, self).validate()
        self.validate_assignment_properties()

    def client(self):
        return super(KeystoneUser, self).client().client

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

        # If there're no args above, keystone raises BadRequest error with
        # message about not enough parameters for updating, so return from
        # this method to prevent raising error.
        if not values:
            return

        values['user'] = user_id
        values['domain'] = domain

        return self.client().users.update(**values)

    def _add_user_to_groups(self, user_id, groups):
        if groups is not None:
            for group_id in groups:
                self.client().users.add_to_group(user_id,
                                                 group_id)

    def _remove_user_from_groups(self, user_id, groups):
        if groups is not None:
            for group_id in groups:
                self.client().users.remove_from_group(user_id,
                                                      group_id)

    def _find_diff(self, updated_prps, stored_prps):
        new_group_ids = list(set(updated_prps or []) - set(stored_prps or []))

        removed_group_ids = list(set(stored_prps or []) -
                                 set(updated_prps or []))

        return new_group_ids, removed_group_ids

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        user = self.client().users.get(self.resource_id)
        return getattr(user, name, None)

    def handle_create(self):
        user_name = (self.properties[self.NAME] or
                     self.physical_resource_name())
        description = self.properties[self.DESCRIPTION]
        domain = self.properties[self.DOMAIN]
        enabled = self.properties[self.ENABLED]
        email = self.properties[self.EMAIL]
        password = self.properties[self.PASSWORD]
        default_project = self.properties[self.DEFAULT_PROJECT]
        groups = self.properties[self.GROUPS]

        user = self.client().users.create(
            name=user_name,
            domain=domain,
            description=description,
            enabled=enabled,
            email=email,
            password=password,
            default_project=default_project)

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
            domain = (prop_diff.get(self.DOMAIN)
                      or self.properties[self.DOMAIN])

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
                    self.properties[self.GROUPS])
                if new_group_ids:
                    self._add_user_to_groups(self.resource_id, new_group_ids)

                if removed_group_ids:
                    self._remove_user_from_groups(self.resource_id,
                                                  removed_group_ids)

            self.update_assignment(prop_diff=prop_diff,
                                   user_id=self.resource_id)

    def parse_live_resource_data(self, resource_properties, resource_data):
        user_reality = {
            self.ROLES: self.parse_list_assignments(user_id=self.resource_id),
            self.DEFAULT_PROJECT: resource_data.get('default_project_id'),
            self.DOMAIN: resource_data.get('domain_id'),
            self.GROUPS: [group.id for group in self.client().groups.list(
                user=self.resource_id)]
        }
        props_keys = [self.NAME, self.DESCRIPTION, self.ENABLED, self.EMAIL]
        for key in props_keys:
            user_reality.update({key: resource_data.get(key)})
        return user_reality

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                if self.properties[self.GROUPS] is not None:
                    self._remove_user_from_groups(
                        self.resource_id,
                        self.properties[self.GROUPS])

                self.client().users.delete(self.resource_id)


def resource_mapping():
    return {
        'OS::Keystone::User': KeystoneUser
    }
