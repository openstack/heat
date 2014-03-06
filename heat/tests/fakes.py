
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

from heat.common import context

"""
A fake server that "responds" to API methods with pre-canned responses.

All of these responses come from the spec, so if for some reason the spec's
wrong the tests might raise AssertionError. I've indicated in comments the
places where actual behavior differs from the spec.
"""


class FakeClient(object):

    def assert_called(self, method, url, body=None, pos=-1):
        """
        Assert than an API method was just called.
        """
        expected = (method, url)
        called = self.client.callstack[pos][0:2]

        assert self.client.callstack, \
            "Expected %s %s but no calls were made." % expected

        assert expected == called, 'Expected %s %s; got %s %s' % \
            (expected + called)

        if body is not None:
            assert self.client.callstack[pos][2] == body

    def assert_called_anytime(self, method, url, body=None):
        """
        Assert than an API method was called anytime in the test.
        """
        expected = (method, url)

        assert self.client.callstack, \
            "Expected %s %s but no calls were made." % expected

        found = False
        for entry in self.client.callstack:
            if expected == entry[0:2]:
                found = True
                break

        assert found, 'Expected %s %s; got %s' % \
            (expected, self.client.callstack)
        if body is not None:
            try:
                assert entry[2] == body
            except AssertionError:
                print(entry[2])
                print("!=")
                print(body)
                raise

        self.client.callstack = []

    def clear_callstack(self):
        self.client.callstack = []

    def authenticate(self):
        pass


class FakeKeystoneClient(object):
    def __init__(self, username='test_user', password='apassword',
                 user_id='1234', access='4567', secret='8901',
                 credential_id='abcdxyz'):
        self.username = username
        self.password = password
        self.user_id = user_id
        self.access = access
        self.secret = secret
        self.credential_id = credential_id

        class FakeCred(object):
            id = self.credential_id
            access = self.access
            secret = self.secret
        self.creds = FakeCred()

        self.auth_token = 'abcd1234'

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

    def url_for(self, **kwargs):
        return 'http://example.com:1234/v1'

    def create_trust_context(self):
        return context.RequestContext(username=self.username,
                                      password=self.password,
                                      is_admin=False,
                                      trust_id='atrust',
                                      trustor_user_id='auser123')

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
