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

import mock
from testtools.matchers import MatchesRegex

from heat.engine.clients.os import swift
from heat.tests.common import HeatTestCase
from heat.tests import utils


class SwiftClientPluginTestCase(HeatTestCase):
    def setUp(self):
        super(SwiftClientPluginTestCase, self).setUp()
        self.swift_client = mock.Mock()
        con = utils.dummy_context()
        c = con.clients
        self.swift_plugin = c.client_plugin('swift')
        self.swift_plugin._client = self.swift_client


class SwiftUtilsTests(SwiftClientPluginTestCase):

    def test_is_valid_temp_url_path(self):
        sc = swift.SwiftClientPlugin

        valids = [
            "/v1/AUTH_demo/c/o",
            "/v1/AUTH_demo/c/o/",
            "/v1/TEST_demo/c/o",
            "/v1/AUTH_demo/c/pseudo_folder/o",
        ]
        for url in valids:
            self.assertTrue(sc.is_valid_temp_url_path(url))

        invalids = [
            "/v2/AUTH_demo/c/o",
            "/v1/AUTH_demo/c//",
            "/v1/AUTH_demo/c/",
            "/AUTH_demo/c//",
            "//AUTH_demo/c/o",
            "//v1/AUTH_demo/c/o",
            "/v1/AUTH_demo/o",
            "/v1/AUTH_demo//o",
            "/v1//c/o",
            "/v1/c/o",
        ]
        for url in invalids:
            self.assertFalse(sc.is_valid_temp_url_path(url))

    def test_get_temp_url(self):
        self.swift_client.url = ("http://fake-host.com:8080/v1/"
                                 "AUTH_test_tenant_id")
        self.swift_client.head_account = mock.Mock(return_value={
            'x-account-meta-temp-url-key': '123456'})
        self.swift_client.post_account = mock.Mock()

        container_name = '1234'  # from stack.id
        stack_name = 'test'
        handle_name = 'foo'
        obj_name = '%s-%s' % (stack_name, handle_name)
        url = self.swift_plugin.get_temp_url(container_name, obj_name)
        self.assertFalse(self.swift_client.post_account.called)
        regexp = ("http://fake-host.com:8080/v1/AUTH_test_tenant_id/%s"
                  "/%s\?temp_url_sig=[0-9a-f]{40}&"
                  "temp_url_expires=[0-9]{10}" %
                  (container_name, obj_name))
        self.assertThat(url, MatchesRegex(regexp))

        timeout = int(url.split('=')[-1])
        self.assertTrue(timeout < swift.MAX_EPOCH)

    def test_get_temp_url_no_account_key(self):
        self.swift_client.url = ("http://fake-host.com:8080/v1/"
                                 "AUTH_test_tenant_id")
        self.swift_client.head_account = mock.Mock(return_value={})
        self.swift_client.post_account = mock.Mock()
        self.assertFalse(self.swift_client.post_account.called)

        container_name = '1234'  # from stack.id
        stack_name = 'test'
        handle_name = 'foo'
        obj_name = '%s-%s' % (stack_name, handle_name)
        self.swift_plugin.get_temp_url(container_name, obj_name)
        self.assertTrue(self.swift_client.post_account.called)

    def test_get_signal_url(self):
        self.swift_client.url = ("http://fake-host.com:8080/v1/"
                                 "AUTH_test_tenant_id")
        self.swift_client.head_account = mock.Mock(return_value={
            'x-account-meta-temp-url-key': '123456'})
        self.swift_client.post_account = mock.Mock()

        container_name = '1234'  # from stack.id
        stack_name = 'test'
        handle_name = 'foo'
        obj_name = '%s-%s' % (stack_name, handle_name)
        url = self.swift_plugin.get_signal_url(container_name, obj_name)
        self.assertTrue(self.swift_client.put_container.called)
        self.assertTrue(self.swift_client.put_object.called)
        regexp = ("http://fake-host.com:8080/v1/AUTH_test_tenant_id/%s"
                  "/%s\?temp_url_sig=[0-9a-f]{40}&"
                  "temp_url_expires=[0-9]{10}" %
                  (container_name, obj_name))
        self.assertThat(url, MatchesRegex(regexp))
