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

from keystoneclient import exceptions

from heat.common import exception
from heat.common import heat_keystoneclient as hkc
from heat.engine.clients import client_plugin
from heat.engine import constraints


class KeystoneClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    service_types = [IDENTITY] = ['identity']

    def _create(self):
        return hkc.KeystoneClient(self.context)

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exceptions.RequestEntityTooLarge)

    def is_conflict(self, ex):
        return isinstance(ex, exceptions.Conflict)

    def get_role_id(self, role):
        try:
            role_obj = self.client().client.roles.get(role)
            return role_obj.id
        except exceptions.NotFound:
            role_list = self.client().client.roles.list(name=role)
            for role_obj in role_list:
                if role_obj.name == role:
                    return role_obj.id

        raise exception.EntityNotFound(entity='KeystoneRole', name=role)

    def get_project_id(self, project):
        try:
            project_obj = self.client().client.projects.get(project)
            return project_obj.id
        except exceptions.NotFound:
            project_list = self.client().client.projects.list(name=project)
            for project_obj in project_list:
                if project_obj.name == project:
                    return project_obj.id

        raise exception.EntityNotFound(entity='KeystoneProject',
                                       name=project)

    def get_domain_id(self, domain):
        try:
            domain_obj = self.client().client.domains.get(domain)
            return domain_obj.id
        except exceptions.NotFound:
            domain_list = self.client().client.domains.list(name=domain)
            for domain_obj in domain_list:
                if domain_obj.name == domain:
                    return domain_obj.id

        raise exception.EntityNotFound(entity='KeystoneDomain', name=domain)

    def get_group_id(self, group):
        try:
            group_obj = self.client().client.groups.get(group)
            return group_obj.id
        except exceptions.NotFound:
            group_list = self.client().client.groups.list(name=group)
            for group_obj in group_list:
                if group_obj.name == group:
                    return group_obj.id

        raise exception.EntityNotFound(entity='KeystoneGroup', name=group)

    def get_service_id(self, service):
        try:
            service_obj = self.client().client.services.get(service)
            return service_obj.id
        except exceptions.NotFound:
            service_list = self.client().client.services.list(name=service)

            if len(service_list) == 1:
                return service_list[0].id
            elif len(service_list) > 1:
                raise exception.KeystoneServiceNameConflict(service=service)
            else:
                raise exception.EntityNotFound(entity='KeystoneService',
                                               name=service)

    def get_user_id(self, user):
        try:
            user_obj = self.client().client.users.get(user)
            return user_obj.id
        except exceptions.NotFound:
            user_list = self.client().client.users.list(name=user)
            for user_obj in user_list:
                if user_obj.name == user:
                    return user_obj.id

        raise exception.EntityNotFound(entity='KeystoneUser', name=user)


class KeystoneRoleConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.EntityNotFound,)

    def validate_with_client(self, client, role):
        client.client_plugin('keystone').get_role_id(role)


class KeystoneDomainConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.EntityNotFound,)

    def validate_with_client(self, client, domain):
        client.client_plugin('keystone').get_domain_id(domain)


class KeystoneProjectConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.EntityNotFound,)

    def validate_with_client(self, client, project):
        client.client_plugin('keystone').get_project_id(project)


class KeystoneGroupConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.EntityNotFound,)

    def validate_with_client(self, client, group):
        client.client_plugin('keystone').get_group_id(group)


class KeystoneServiceConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.EntityNotFound,
                           exception.KeystoneServiceNameConflict,)

    def validate_with_client(self, client, service):
        client.client_plugin('keystone').get_service_id(service)


class KeystoneUserConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.EntityNotFound,)

    def validate_with_client(self, client, user):
        client.client_plugin('keystone').get_user_id(user)
