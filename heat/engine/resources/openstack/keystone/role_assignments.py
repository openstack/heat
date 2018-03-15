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


class KeystoneRoleAssignmentMixin(object):
    """Implements role assignments between user/groups and project/domain.

    For example::

        heat_template_version: 2013-05-23

        parameters:
          ... Group or User parameters
          group_role:
            type: string
            description: role
          group_role_domain:
            type: string
            description: group role domain
          group_role_project:
            type: string
            description: group role project

        resources:
          admin_group:
            type: OS::Keystone::Group OR OS::Keystone::User
            properties:
              ... Group or User properties
              roles:
                - role: {get_param: group_role}
                  domain: {get_param: group_role_domain}
                - role: {get_param: group_role}
                  project: {get_param: group_role_project}
    """

    PROPERTIES = (
        ROLES
    ) = (
        'roles'
    )

    _ROLES_MAPPING_PROPERTIES = (
        ROLE, DOMAIN, PROJECT
    ) = (
        'role', 'domain', 'project'
    )

    mixin_properties_schema = {
        ROLES: properties.Schema(
            properties.Schema.LIST,
            _('List of role assignments.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                _('Map between role with either project or domain.'),
                schema={
                    ROLE: properties.Schema(
                        properties.Schema.STRING,
                        _('Keystone role.'),
                        required=True,
                        constraints=([constraints.
                                     CustomConstraint('keystone.role')])
                    ),
                    PROJECT: properties.Schema(
                        properties.Schema.STRING,
                        _('Keystone project.'),
                        constraints=([constraints.
                                     CustomConstraint('keystone.project')])
                    ),
                    DOMAIN: properties.Schema(
                        properties.Schema.STRING,
                        _('Keystone domain.'),
                        constraints=([constraints.
                                     CustomConstraint('keystone.domain')])
                    ),
                }
            ),
            update_allowed=True
        )
    }

    def _add_role_assignments_to_group(self, group_id, role_assignments):
        for role_assignment in self._normalize_to_id(role_assignments):
            if role_assignment.get(self.PROJECT) is not None:
                self.client().roles.grant(
                    role=role_assignment.get(self.ROLE),
                    project=role_assignment.get(self.PROJECT),
                    group=group_id
                )
            elif role_assignment.get(self.DOMAIN) is not None:
                self.client().roles.grant(
                    role=role_assignment.get(self.ROLE),
                    domain=role_assignment.get(self.DOMAIN),
                    group=group_id
                )

    def _add_role_assignments_to_user(self, user_id, role_assignments):
        for role_assignment in self._normalize_to_id(role_assignments):
            if role_assignment.get(self.PROJECT) is not None:
                self.client().roles.grant(
                    role=role_assignment.get(self.ROLE),
                    project=role_assignment.get(self.PROJECT),
                    user=user_id
                )
            elif role_assignment.get(self.DOMAIN) is not None:
                self.client().roles.grant(
                    role=role_assignment.get(self.ROLE),
                    domain=role_assignment.get(self.DOMAIN),
                    user=user_id
                )

    def _remove_role_assignments_from_group(self, group_id, role_assignments,
                                            current_assignments):
        for role_assignment in self._normalize_to_id(role_assignments):
            if role_assignment in current_assignments:
                if role_assignment.get(self.PROJECT) is not None:
                    self.client().roles.revoke(
                        role=role_assignment.get(self.ROLE),
                        project=role_assignment.get(self.PROJECT),
                        group=group_id
                    )
                elif role_assignment.get(self.DOMAIN) is not None:
                    self.client().roles.revoke(
                        role=role_assignment.get(self.ROLE),
                        domain=role_assignment.get(self.DOMAIN),
                        group=group_id
                    )

    def _remove_role_assignments_from_user(self, user_id, role_assignments,
                                           current_assignments):
        for role_assignment in self._normalize_to_id(role_assignments):
            if role_assignment in current_assignments:
                if role_assignment.get(self.PROJECT) is not None:
                    self.client().roles.revoke(
                        role=role_assignment.get(self.ROLE),
                        project=role_assignment.get(self.PROJECT),
                        user=user_id
                    )
                elif role_assignment.get(self.DOMAIN) is not None:
                    self.client().roles.revoke(
                        role=role_assignment.get(self.ROLE),
                        domain=role_assignment.get(self.DOMAIN),
                        user=user_id
                    )

    def _normalize_to_id(self, role_assignment_prps):
        role_assignments = []
        if role_assignment_prps is None:
            return role_assignments

        for role_assignment in role_assignment_prps:
            role = role_assignment.get(self.ROLE)
            project = role_assignment.get(self.PROJECT)
            domain = role_assignment.get(self.DOMAIN)

            role_assignments.append({
                self.ROLE: self.client_plugin().get_role_id(role),
                self.PROJECT: (self.client_plugin().
                               get_project_id(project)) if project else None,
                self.DOMAIN: (self.client_plugin().
                              get_domain_id(domain)) if domain else None
            })
        return role_assignments

    def _find_differences(self, updated_prps, stored_prps):
        updated_role_project_assignments = []
        updated_role_domain_assignments = []

        # Split the properties into two set of role assignments
        # (project, domain) from updated properties
        for role_assignment in updated_prps or []:
            if role_assignment.get(self.PROJECT) is not None:
                updated_role_project_assignments.append(
                    '%s:%s' % (
                        role_assignment[self.ROLE],
                        role_assignment[self.PROJECT]))
            elif (role_assignment.get(self.DOMAIN)
                  is not None):
                updated_role_domain_assignments.append(
                    '%s:%s' % (role_assignment[self.ROLE],
                               role_assignment[self.DOMAIN]))

        stored_role_project_assignments = []
        stored_role_domain_assignments = []

        # Split the properties into two set of role assignments
        # (project, domain) from updated properties
        for role_assignment in (stored_prps or []):
            if role_assignment.get(self.PROJECT) is not None:
                stored_role_project_assignments.append(
                    '%s:%s' % (
                        role_assignment[self.ROLE],
                        role_assignment[self.PROJECT]))
            elif (role_assignment.get(self.DOMAIN)
                  is not None):
                stored_role_domain_assignments.append(
                    '%s:%s' % (role_assignment[self.ROLE],
                               role_assignment[self.DOMAIN]))

        new_role_assignments = []
        removed_role_assignments = []
        # NOTE: finding the diff of list of strings is easier by using 'set'
        #       so properties are converted to string in above sections
        # New items
        for item in (set(updated_role_project_assignments) -
                     set(stored_role_project_assignments)):
            new_role_assignments.append(
                {self.ROLE: item[:item.find(':')],
                 self.PROJECT: item[item.find(':') + 1:]}
            )

        for item in (set(updated_role_domain_assignments) -
                     set(stored_role_domain_assignments)):
            new_role_assignments.append(
                {self.ROLE: item[:item.find(':')],
                 self.DOMAIN: item[item.find(':') + 1:]}
            )

        # Old items
        for item in (set(stored_role_project_assignments) -
                     set(updated_role_project_assignments)):
            removed_role_assignments.append(
                {self.ROLE: item[:item.find(':')],
                 self.PROJECT: item[item.find(':') + 1:]}
            )
        for item in (set(stored_role_domain_assignments) -
                     set(updated_role_domain_assignments)):
            removed_role_assignments.append(
                {self.ROLE: item[:item.find(':')],
                 self.DOMAIN: item[item.find(':') + 1:]}
            )

        return new_role_assignments, removed_role_assignments

    def create_assignment(self, user_id=None, group_id=None):
        if self.properties.get(self.ROLES) is not None:
            if user_id is not None:
                self._add_role_assignments_to_user(
                    user_id,
                    self.properties.get(self.ROLES))
            elif group_id is not None:
                self._add_role_assignments_to_group(
                    group_id,
                    self.properties.get(self.ROLES))

    def update_assignment(self, prop_diff, user_id=None, group_id=None):
        # if there is no change do not update
        if self.ROLES in prop_diff:
            (new_role_assignments,
             removed_role_assignments) = self._find_differences(
                prop_diff.get(self.ROLES),
                self.properties[self.ROLES])

            if len(new_role_assignments) > 0:
                if user_id is not None:
                    self._add_role_assignments_to_user(
                        user_id,
                        new_role_assignments)
                elif group_id is not None:
                    self._add_role_assignments_to_group(
                        group_id,
                        new_role_assignments)

            if len(removed_role_assignments) > 0:
                current_assignments = self.parse_list_assignments(
                    user_id=user_id, group_id=group_id)
                if user_id is not None:
                    self._remove_role_assignments_from_user(
                        user_id,
                        removed_role_assignments,
                        current_assignments)
                elif group_id is not None:
                    self._remove_role_assignments_from_group(
                        group_id,
                        removed_role_assignments,
                        current_assignments)

    def delete_assignment(self, user_id=None, group_id=None):
        if self.properties[self.ROLES] is not None:
            current_assignments = self.parse_list_assignments(
                user_id=user_id, group_id=group_id)
            if user_id is not None:
                self._remove_role_assignments_from_user(
                    user_id,
                    (self.properties[self.ROLES]),
                    current_assignments)
            elif group_id is not None:
                self._remove_role_assignments_from_group(
                    group_id,
                    (self.properties[self.ROLES]),
                    current_assignments)

    def validate_assignment_properties(self):
        if self.properties.get(self.ROLES) is not None:
            for role_assignment in self.properties.get(self.ROLES):
                project = role_assignment.get(self.PROJECT)
                domain = role_assignment.get(self.DOMAIN)

                if project is not None and domain is not None:
                    raise exception.ResourcePropertyConflict(self.PROJECT,
                                                             self.DOMAIN)

                if project is None and domain is None:
                    msg = _('Either project or domain must be specified for'
                            ' role %s') % role_assignment.get(self.ROLE)
                    raise exception.StackValidationFailed(message=msg)

    def parse_list_assignments(self, user_id=None, group_id=None):
        """Method used for get_live_state implementation in other resources."""
        assignments = []
        roles = []
        if user_id is not None:
            assignments = self.client().role_assignments.list(user=user_id)
        elif group_id is not None:
            assignments = self.client().role_assignments.list(group=group_id)
        for assignment in assignments:
            values = assignment.to_dict()
            if not values.get('role') or not values.get('role').get('id'):
                continue
            role = {
                self.ROLE: values['role']['id'],
                self.DOMAIN: (values.get('scope') and
                              values['scope'].get('domain') and
                              values['scope'].get('domain').get('id')),
                self.PROJECT: (values.get('scope') and
                               values['scope'].get('project') and
                               values['scope'].get('project').get('id')),
            }
            roles.append(role)
        return roles


class KeystoneUserRoleAssignment(resource.Resource,
                                 KeystoneRoleAssignmentMixin):
    """Resource for granting roles to a user.

    Resource for specifying users and their's roles.
    """

    support_status = support.SupportStatus(
        version='5.0.0',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    PROPERTIES = (
        USER,
    ) = (
        'user',
    )

    properties_schema = {
        USER: properties.Schema(
            properties.Schema.STRING,
            _('Name or id of keystone user.'),
            required=True,
            update_allowed=True,
            constraints=[constraints.CustomConstraint('keystone.user')]
        )
    }

    properties_schema.update(
        KeystoneRoleAssignmentMixin.mixin_properties_schema)

    def client(self):
        return super(KeystoneUserRoleAssignment, self).client().client

    @property
    def user_id(self):
        try:
            return self.client_plugin().get_user_id(
                self.properties.get(self.USER))
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            return None

    def handle_create(self):
        self.create_assignment(user_id=self.user_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self.update_assignment(user_id=self.user_id, prop_diff=prop_diff)

    def handle_delete(self):
        self.delete_assignment(user_id=self.user_id)

    def validate(self):
        super(KeystoneUserRoleAssignment, self).validate()
        self.validate_assignment_properties()


class KeystoneGroupRoleAssignment(resource.Resource,
                                  KeystoneRoleAssignmentMixin):
    """Resource for granting roles to a group.

    Resource for specifying groups and their's roles.
    """

    support_status = support.SupportStatus(
        version='5.0.0',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    PROPERTIES = (
        GROUP,
    ) = (
        'group',
    )

    properties_schema = {
        GROUP: properties.Schema(
            properties.Schema.STRING,
            _('Name or id of keystone group.'),
            required=True,
            update_allowed=True,
            constraints=[constraints.CustomConstraint('keystone.group')]
        )
    }

    properties_schema.update(
        KeystoneRoleAssignmentMixin.mixin_properties_schema)

    def client(self):
        return super(KeystoneGroupRoleAssignment, self).client().client

    @property
    def group_id(self):
        try:
            return self.client_plugin().get_group_id(
                self.properties.get(self.GROUP))
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            return None

    def handle_create(self):
        self.create_assignment(group_id=self.group_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self.update_assignment(group_id=self.group_id, prop_diff=prop_diff)

    def handle_delete(self):
        self.delete_assignment(group_id=self.group_id)

    def validate(self):
        super(KeystoneGroupRoleAssignment, self).validate()
        self.validate_assignment_properties()


def resource_mapping():
    return {
        'OS::Keystone::UserRoleAssignment': KeystoneUserRoleAssignment,
        'OS::Keystone::GroupRoleAssignment': KeystoneGroupRoleAssignment
    }
