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

import datetime

import mock
import pytz
from testtools import matchers

from heat.engine.clients.os import swift
from heat.tests import common
from heat.tests import utils


class SwiftClientPluginTestCase(common.HeatTestCase):
    def setUp(self):
        super(SwiftClientPluginTestCase, self).setUp()
        self.swift_client = mock.Mock()
        self.context = utils.dummy_context()
        self.context.tenant = "demo"
        c = self.context.clients
        self.swift_plugin = c.client_plugin('swift')
        self.swift_plugin.client = lambda: self.swift_client


class SwiftUtilsTest(SwiftClientPluginTestCase):

    def test_is_valid_temp_url_path(self):

        valids = [
            "/v1/AUTH_demo/c/o",
            "/v1/AUTH_demo/c/o/",
            "/v1/TEST_demo/c/o",
            "/v1/AUTH_demo/c/pseudo_folder/o",
        ]
        for url in valids:
            self.assertTrue(self.swift_plugin.is_valid_temp_url_path(url))

        invalids = [
            "/v2/AUTH_demo/c/o",
            "/v1/AUTH_demo/c//",
            "/v1/AUTH_demo/c/",
            "/AUTH_demo/c//",
            "//AUTH_demo/c/o",
            "//v1/AUTH_demo/c/o",
            "/v1/AUTH_demo/o",
            "/v1/AUTH_demo//o",
            "/v1/AUTH_d3mo//o",
            "/v1//c/o",
            "/v1/c/o",
        ]
        for url in invalids:
            self.assertFalse(self.swift_plugin.is_valid_temp_url_path(url))

    def test_get_temp_url(self):
        self.swift_client.url = ("http://fake-host.com:8080/v1/"
                                 "AUTH_demo")
        self.swift_client.head_account = mock.Mock(return_value={
            'x-account-meta-temp-url-key': '123456'})
        self.swift_client.post_account = mock.Mock()

        container_name = '1234'  # from stack.id
        stack_name = 'test'
        handle_name = 'foo'
        obj_name = '%s-%s' % (stack_name, handle_name)
        url = self.swift_plugin.get_temp_url(container_name, obj_name)
        self.assertFalse(self.swift_client.post_account.called)
        regexp = ("http://fake-host.com:8080/v1/AUTH_demo/%s"
                  r"/%s\?temp_url_sig=[0-9a-f]{40}&"
                  "temp_url_expires=[0-9]{10}" %
                  (container_name, obj_name))
        self.assertThat(url, matchers.MatchesRegex(regexp))

        timeout = int(url.split('=')[-1])
        self.assertLess(timeout, swift.MAX_EPOCH)

    def test_get_temp_url_no_account_key(self):
        self.swift_client.url = ("http://fake-host.com:8080/v1/"
                                 "AUTH_demo")
        head_account = {}

        def post_account(data):
            head_account.update(data)

        self.swift_client.head_account = mock.Mock(return_value=head_account)
        self.swift_client.post_account = post_account

        container_name = '1234'  # from stack.id
        stack_name = 'test'
        handle_name = 'foo'
        obj_name = '%s-%s' % (stack_name, handle_name)

        self.assertNotIn('x-account-meta-temp-url-key', head_account)
        self.swift_plugin.get_temp_url(container_name, obj_name)
        self.assertIn('x-account-meta-temp-url-key', head_account)

    def test_get_signal_url(self):
        self.swift_client.url = ("http://fake-host.com:8080/v1/"
                                 "AUTH_demo")
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
        regexp = ("http://fake-host.com:8080/v1/AUTH_demo/%s"
                  r"/%s\?temp_url_sig=[0-9a-f]{40}&"
                  "temp_url_expires=[0-9]{10}" %
                  (container_name, obj_name))
        self.assertThat(url, matchers.MatchesRegex(regexp))

    def test_parse_last_modified(self):
        self.assertIsNone(self.swift_plugin.parse_last_modified(None))
        now = datetime.datetime(
            2015, 2, 5, 1, 4, 40, 0, pytz.timezone('GMT'))
        now_naive = datetime.datetime(
            2015, 2, 5, 1, 4, 40, 0)
        last_modified = now.strftime('%a, %d %b %Y %H:%M:%S %Z')
        self.assertEqual('Thu, 05 Feb 2015 01:04:40 GMT', last_modified)
        self.assertEqual(
            now_naive,
            self.swift_plugin.parse_last_modified(last_modified))
