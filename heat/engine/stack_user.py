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

import keystoneclient.exceptions as kc_exception

from heat.common import exception
from heat.common.i18n import _
from heat.engine import resource
from heat.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class StackUser(resource.Resource):

    # Subclasses create a user, and optionally keypair associated with a
    # resource in a stack. Users are created  in the heat stack user domain
    # (in a project specific to the stack)
    def __init__(self, name, json_snippet, stack):
        super(StackUser, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        self._create_user()

    def _create_user(self):
        # Check for stack user project, create if not yet set
        if not self.stack.stack_user_project_id:
            project_id = self.keystone().create_stack_domain_project(
                self.stack.id)
            self.stack.set_stack_user_project_id(project_id)

        # Create a keystone user in the stack domain project
        user_id = self.keystone().create_stack_domain_user(
            username=self.physical_resource_name(),
            password=getattr(self, 'password', None),
            project_id=self.stack.stack_user_project_id)

        # Store the ID in resource data, for compatibility with SignalResponder
        self.data_set('user_id', user_id)

    def _user_token(self):
        project_id = self.stack.stack_user_project_id
        if not project_id:
            raise ValueError(_("Can't get user token, user not yet created"))
        password = getattr(self, 'password', None)
        # FIXME(shardy): the create and getattr here could allow insane
        # passwords, e.g a zero length string, if these happen it almost
        # certainly means a bug elsewhere in heat, so add assertion to catch
        if password is None:
            raise ValueError(_("Can't get user token without password"))

        return self.keystone().stack_domain_user_token(
            username=self.physical_resource_name(),
            project_id=project_id, password=password)

    def _get_user_id(self):
        user_id = self.data().get('user_id')
        if user_id:
            return user_id
        else:
            # FIXME(shardy): This is a legacy hack for backwards compatibility
            # remove after an appropriate transitional period...
            # Assume this is a resource that was created with
            # a previous version of heat and that the resource_id
            # is the user_id
            if self.resource_id:
                self.data_set('user_id', self.resource_id)
                return self.resource_id

    def handle_delete(self):
        self._delete_user()

    def _delete_user(self):
        user_id = self._get_user_id()
        if user_id is None:
            return
        try:
            self.keystone().delete_stack_domain_user(
                user_id=user_id, project_id=self.stack.stack_user_project_id)
        except kc_exception.NotFound:
            pass
        except ValueError:
            # FIXME(shardy): This is a legacy delete path for backwards
            # compatibility with resources created before the migration
            # to stack_user.StackUser domain users.  After an appropriate
            # transitional period, this should be removed.
            LOG.warning(_('Reverting to legacy user delete path'))
            try:
                self.keystone().delete_stack_user(user_id)
            except kc_exception.NotFound:
                pass
        for data_key in ('credential_id', 'access_key', 'secret_key'):
            self.data_delete(data_key)

    def handle_suspend(self):
        user_id = self._get_user_id()
        try:
            self.keystone().disable_stack_domain_user(
                user_id=user_id, project_id=self.stack.stack_user_project_id)
        except ValueError:
            # FIXME(shardy): This is a legacy path for backwards compatibility
            self.keystone().disable_stack_user(user_id=user_id)

    def handle_resume(self):
        user_id = self._get_user_id()
        try:
            self.keystone().enable_stack_domain_user(
                user_id=user_id, project_id=self.stack.stack_user_project_id)
        except ValueError:
            # FIXME(shardy): This is a legacy path for backwards compatibility
            self.keystone().enable_stack_user(user_id=user_id)

    def _create_keypair(self):
        # Subclasses may optionally call this in handle_create to create
        # an ec2 keypair associated with the user, the resulting keys are
        # stored in resource_data
        user_id = self._get_user_id()
        kp = self.keystone().create_stack_domain_user_keypair(
            user_id=user_id, project_id=self.stack.stack_user_project_id)
        if not kp:
            raise exception.Error(_("Error creating ec2 keypair for user %s") %
                                  user_id)
        else:
            try:
                credential_id = kp.id
            except AttributeError:
                # keystone v2 keypairs do not have an id attribute. Use the
                # access key instead.
                credential_id = kp.access
            self.data_set('credential_id', credential_id, redact=True)
            self.data_set('access_key', kp.access, redact=True)
            self.data_set('secret_key', kp.secret, redact=True)
        return kp

    def _delete_keypair(self):
        # Subclasses may optionally call this to delete a keypair created
        # via _create_keypair
        user_id = self._get_user_id()
        credential_id = self.data().get('credential_id')
        if not credential_id:
            return

        try:
            self.keystone().delete_stack_domain_user_keypair(
                user_id=user_id, project_id=self.stack.stack_user_project_id,
                credential_id=credential_id)
        except ValueError:
            self.keystone().delete_ec2_keypair(
                user_id=user_id, credential_id=credential_id)

        for data_key in ('access_key', 'secret_key', 'credential_id'):
            self.data_delete(data_key)
