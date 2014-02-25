
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

from heat.db import api as db_api
from heat.common import exception
from heat.engine import resource

from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _


logger = logging.getLogger(__name__)


class StackUser(resource.Resource):

    # Subclasses create a user, and optionally keypair
    # associated with a resource in a stack
    def handle_create(self):
        self._create_user()

    def _create_user(self):
        user_id = self.keystone().create_stack_user(
            self.physical_resource_name())

        db_api.resource_data_set(self, 'user_id', user_id)

    def _get_user_id(self):
        try:
            return db_api.resource_data_get(self, 'user_id')
        except exception.NotFound:
            # Assume this is a resource that was created with
            # a previous version of heat and that the resource_id
            # is the user_id
            if self.resource_id:
                db_api.resource_data_set(self, 'user_id', self.resource_id)
                return self.resource_id

    def handle_delete(self):
        self._delete_user()

    def _delete_user(self):
        user_id = self._get_user_id()
        if user_id is None:
            return
        try:
            self.keystone().delete_stack_user(user_id)
        except kc_exception.NotFound:
            pass
        for data_key in ('ec2_signed_url', 'access_key', 'secret_key',
                         'credential_id'):
            try:
                db_api.resource_data_delete(self, data_key)
            except exception.NotFound:
                pass

    def _create_keypair(self):
        # Subclasses may optionally call this in handle_create to create
        # an ec2 keypair associated with the user, the resulting keys are
        # stored in resource_data
        user_id = self._get_user_id()
        kp = self.keystone().create_ec2_keypair(user_id)
        if not kp:
            raise exception.Error(_("Error creating ec2 keypair for user %s") %
                                  user_id)
        else:
            db_api.resource_data_set(self, 'credential_id', kp.id,
                                     redact=True)
            db_api.resource_data_set(self, 'access_key', kp.access,
                                     redact=True)
            db_api.resource_data_set(self, 'secret_key', kp.secret,
                                     redact=True)
