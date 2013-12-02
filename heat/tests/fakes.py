# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
                 user_id='1234', access='4567', secret='8901'):
        self.username = username
        self.password = password
        self.user_id = user_id
        self.access = access
        self.secret = secret
        self.creds = None
        self.auth_token = 'abcd1234'

    def create_stack_user(self, username, password=''):
        self.username = username
        return self.user_id

    def delete_stack_user(self, user_id):
        self.user_id = None

    def get_ec2_keypair(self, user_id):
        if user_id == self.user_id:
            if not self.creds:
                class FakeCred(object):
                    access = self.access
                    secret = self.secret
                self.creds = FakeCred()
            return self.creds

    def delete_ec2_keypair(self, user_id, access):
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
                                      trust_id='atrust',
                                      trustor_user_id='auser123')

    def delete_trust(self, trust_id):
        pass
