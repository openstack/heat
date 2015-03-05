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

import exceptions

from keystoneclient import exceptions as keystone_exceptions

from heat.engine.clients.os import keystone
from heat.engine import constraints


class KeystoneClientPlugin(keystone.KeystoneClientPlugin):

    def get_role_id(self, role):
        try:
            role_obj = self.client().client.roles.get(role)
            return role_obj.id
        except keystone_exceptions.NotFound:
            role_list = self.client().client.roles.list(name=role)
            for role_obj in role_list:
                if role_obj.name == role:
                    return role_obj.id

        raise exceptions.KeystoneRoleNotFound(role_id=role)

    def get_project_id(self, project):
        try:
            project_obj = self.client().client.projects.get(project)
            return project_obj.id
        except keystone_exceptions.NotFound:
            project_list = self.client().client.projects.list(name=project)
            for project_obj in project_list:
                if project_obj.name == project:
                    return project_obj.id

        raise exceptions.KeystoneProjectNotFound(project_id=project)

    def get_domain_id(self, domain):
        try:
            domain_obj = self.client().client.domains.get(domain)
            return domain_obj.id
        except keystone_exceptions.NotFound:
            domain_list = self.client().client.domains.list(name=domain)
            for domain_obj in domain_list:
                if domain_obj.name == domain:
                    return domain_obj.id

        raise exceptions.KeystoneDomainNotFound(domain_id=domain)

    def get_group_id(self, group):
        try:
            group_obj = self.client().client.groups.get(group)
            return group_obj.id
        except keystone_exceptions.NotFound:
            group_list = self.client().client.groups.list(name=group)
            for group_obj in group_list:
                if group_obj.name == group:
                    return group_obj.id

        raise exceptions.KeystoneGroupNotFound(group_id=group)


class KeystoneRoleConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.KeystoneRoleNotFound,)

    def validate_with_client(self, client, role):
        client.client_plugin('keystone').get_role_id(role)


class KeystoneDomainConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.KeystoneDomainNotFound,)

    def validate_with_client(self, client, domain):
        client.client_plugin('keystone').get_domain_id(domain)


class KeystoneProjectConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.KeystoneProjectNotFound,)

    def validate_with_client(self, client, project):
        client.client_plugin('keystone').get_project_id(project)


class KeystoneGroupConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.KeystoneGroupNotFound,)

    def validate_with_client(self, client, group):
        client.client_plugin('keystone').get_group_id(group)
