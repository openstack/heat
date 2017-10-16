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

"""A fake FakeKeystoneClient. This can be used during some runtime
scenarios where you want to disable Heat's internal Keystone dependencies
entirely. One example is the TripleO Undercloud installer.

To use this class at runtime set to following heat.conf config setting:

  keystone_backend = heat.engine.clients.os.keystone.fake_keystoneclient\
  .FakeKeystoneClient

"""

from keystoneauth1 import session

from heat.common import context


class FakeKeystoneClient(object):
    def __init__(self, username='test_username', password='password',
                 user_id='1234', access='4567', secret='8901',
                 credential_id='abcdxyz', auth_token='abcd1234',
                 context=None, stack_domain_id='4321', client=None):
        self.username = username
        self.password = password
        self.user_id = user_id
        self.access = access
        self.secret = secret
        self.session = session.Session()
        self.credential_id = credential_id
        self.token = auth_token
        self.context = context
        self.v3_endpoint = 'http://localhost:5000/v3'
        self.stack_domain_id = stack_domain_id
        self.client = client

        class FakeCred(object):
            id = self.credential_id
            access = self.access
            secret = self.secret
        self.creds = FakeCred()

    def create_stack_user(self, username, password=''):
        self.username = username
        return self.user_id

    def delete_stack_user(self, user_id):
        self.user_id = None

    def get_ec2_keypair(self, access, user_id):
        if user_id == self.user_id:
            if access == self.access:
                return self.creds
            else:
                raise ValueError("Unexpected access %s" % access)
        else:
            raise ValueError("Unexpected user_id %s" % user_id)

    def create_ec2_keypair(self, user_id):
        if user_id == self.user_id:
            return self.creds

    def delete_ec2_keypair(self, credential_id=None, user_id=None,
                           access=None):
        if user_id == self.user_id and access == self.creds.access:
            self.creds = None
        else:
            raise Exception('Incorrect user_id or access')

    def enable_stack_user(self, user_id):
        pass

    def disable_stack_user(self, user_id):
        pass

    def create_trust_context(self):
        return context.RequestContext(username=self.username,
                                      password=self.password,
                                      is_admin=False,
                                      trust_id='atrust',
                                      trustor_user_id=self.user_id)

    def delete_trust(self, trust_id):
        pass

    def delete_stack_domain_project(self, project_id):
        pass

    def create_stack_domain_project(self, stack_id):
        return 'aprojectid'

    def create_stack_domain_user(self, username, project_id, password=None):
        return self.user_id

    def delete_stack_domain_user(self, user_id, project_id):
        pass

    def create_stack_domain_user_keypair(self, user_id, project_id):
        return self.creds

    def enable_stack_domain_user(self, user_id, project_id):
        pass

    def disable_stack_domain_user(self, user_id, project_id):
        pass

    def delete_stack_domain_user_keypair(self, user_id, project_id,
                                         credential_id):
        pass

    def stack_domain_user_token(self, user_id, project_id, password):
        return 'adomainusertoken'
