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

"""A fake server that "responds" to API methods with pre-canned responses.

All of these responses come from the spec, so if for some reason the spec's
wrong the tests might raise AssertionError. I've indicated in comments the
places where actual behavior differs from the spec.
"""

from keystoneauth1 import plugin
import mock


class FakeClient(object):

    def assert_called(self, method, url, body=None, pos=-1):
        """Assert that an API method was just called."""
        expected = (method, url)
        called = self.client.callstack[pos][0:2]

        assert self.client.callstack, ("Expected %s %s "
                                       "but no calls were made." % expected)

        assert expected == called, 'Expected %s %s; got %s %s' % (
            expected + called)

        if body is not None:
            assert self.client.callstack[pos][2] == body

    def assert_called_anytime(self, method, url, body=None):
        """Assert that an API method was called anytime in the test."""
        expected = (method, url)

        assert self.client.callstack, ("Expected %s %s but no calls "
                                       "were made." % expected)

        found = False
        for entry in self.client.callstack:
            if expected == entry[0:2]:
                found = True
                break

        assert found, 'Expected %s %s; got %s' % (expected,
                                                  self.client.callstack)
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


class FakeAuth(plugin.BaseAuthPlugin):

    def __init__(self, auth_token='abcd1234', only_services=None):
        self.auth_token = auth_token
        self.only_services = only_services

    def get_token(self, session, **kwargs):
        return self.auth_token

    def get_endpoint(self, session, service_type=None, **kwargs):
        if (self.only_services is not None and
                service_type not in self.only_services):
            return None

        return 'http://example.com:1234/v1'

    def get_auth_ref(self, session):
        return mock.Mock()

    def get_access(self, sesssion):
        return FakeAccessInfo([], None, None)


class FakeAccessInfo(object):
    def __init__(self, roles, user_domain, project_domain):
        self.roles = roles
        self.user_domain = user_domain
        self.project_domain = project_domain

    @property
    def role_names(self):
        return self.roles

    @property
    def user_domain_id(self):
        return self.user_domain

    @property
    def project_domain_id(self):
        return self.project_domain


class FakeEventSink(object):

    def __init__(self, evt):
        self.events = []
        self.evt = evt

    def consume(self, stack, event):
        self.events.append(event)
        self.evt.send(None)
