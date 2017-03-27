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

import contextlib
import email
import uuid

import mock

from heat.common import exception as exc
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils


class MultipartMimeTest(common.HeatTestCase):

    def setUp(self):
        super(MultipartMimeTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.init_config()

    def init_config(self, parts=None):
        parts = parts or []
        stack = parser.Stack(
            self.ctx, 'software_config_test_stack',
            template.Template({
                'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'config_mysql': {
                        'Type': 'OS::Heat::MultipartMime',
                        'Properties': {
                            'parts': parts
                        }}}}))
        self.config = stack['config_mysql']
        self.rpc_client = mock.MagicMock()
        self.config._rpc_client = self.rpc_client

    def test_handle_create(self):
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        sc = {'id': config_id}
        self.rpc_client.create_software_config.return_value = sc
        self.config.id = 55
        self.config.uuid = uuid.uuid4().hex
        self.config.handle_create()
        self.assertEqual(config_id, self.config.resource_id)
        kwargs = self.rpc_client.create_software_config.call_args[1]
        self.assertEqual({
            'name': self.config.physical_resource_name(),
            'config': self.config.message,
            'group': 'Heat::Ungrouped'
        }, kwargs)

    def test_get_message_not_none(self):
        self.config.message = 'Not none'
        result = self.config.get_message()
        self.assertEqual('Not none', result)

    def test_get_message_empty_list(self):
        parts = []
        self.init_config(parts=parts)
        result = self.config.get_message()
        message = email.message_from_string(result)
        self.assertTrue(message.is_multipart())

    def test_get_message_text(self):
        parts = [{
            'config': '1e0e5a60-2843-4cfd-9137-d90bdf18eef5',
            'type': 'text'
        }]
        self.init_config(parts=parts)
        self.rpc_client.show_software_config.return_value = {
            'config': '#!/bin/bash'
        }
        result = self.config.get_message()
        self.assertEqual(
            '1e0e5a60-2843-4cfd-9137-d90bdf18eef5',
            self.rpc_client.show_software_config.call_args[0][1])

        message = email.message_from_string(result)
        self.assertTrue(message.is_multipart())
        subs = message.get_payload()
        self.assertEqual(1, len(subs))
        self.assertEqual('#!/bin/bash', subs[0].get_payload())

    def test_get_message_fail_back(self):
        parts = [{
            'config': '2e0e5a60-2843-4cfd-9137-d90bdf18eef5',
            'type': 'text'
        }]
        self.init_config(parts=parts)

        @contextlib.contextmanager
        def exc_filter():
            try:
                yield
            except exc.NotFound:
                pass

        self.rpc_client.ignore_error_by_name.return_value = exc_filter()
        self.rpc_client.show_software_config.side_effect = exc.NotFound()

        result = self.config.get_message()

        self.assertEqual(
            '2e0e5a60-2843-4cfd-9137-d90bdf18eef5',
            self.rpc_client.show_software_config.call_args[0][1])

        message = email.message_from_string(result)
        self.assertTrue(message.is_multipart())
        subs = message.get_payload()
        self.assertEqual(1, len(subs))
        self.assertEqual('2e0e5a60-2843-4cfd-9137-d90bdf18eef5',
                         subs[0].get_payload())

    def test_get_message_non_uuid(self):
        parts = [{
            'config': 'http://192.168.122.36:8000/v1/waitcondition/'
        }]
        self.init_config(parts=parts)
        result = self.config.get_message()
        message = email.message_from_string(result)
        self.assertTrue(message.is_multipart())
        subs = message.get_payload()
        self.assertEqual(1, len(subs))
        self.assertEqual('http://192.168.122.36:8000/v1/waitcondition/',
                         subs[0].get_payload())

    def test_get_message_text_with_filename(self):
        parts = [{
            'config': '1e0e5a60-2843-4cfd-9137-d90bdf18eef5',
            'type': 'text',
            'filename': '/opt/stack/configure.d/55-heat-config'
        }]
        self.init_config(parts=parts)
        self.rpc_client.show_software_config.return_value = {
            'config': '#!/bin/bash'
        }
        result = self.config.get_message()

        self.assertEqual(
            '1e0e5a60-2843-4cfd-9137-d90bdf18eef5',
            self.rpc_client.show_software_config.call_args[0][1])

        message = email.message_from_string(result)
        self.assertTrue(message.is_multipart())
        subs = message.get_payload()
        self.assertEqual(1, len(subs))
        self.assertEqual('#!/bin/bash', subs[0].get_payload())
        self.assertEqual(parts[0]['filename'], subs[0].get_filename())

    def test_get_message_multi_part(self):
        multipart = ('Content-Type: multipart/mixed; '
                     'boundary="===============2579792489038011818=="\n'
                     'MIME-Version: 1.0\n'
                     '\n--===============2579792489038011818=='
                     '\nContent-Type: text; '
                     'charset="us-ascii"\n'
                     'MIME-Version: 1.0\n'
                     'Content-Transfer-Encoding: 7bit\n'
                     'Content-Disposition: attachment;\n'
                     ' filename="/opt/stack/configure.d/55-heat-config"\n'
                     '#!/bin/bash\n'
                     '--===============2579792489038011818==--\n')
        parts = [{
            'config': '1e0e5a60-2843-4cfd-9137-d90bdf18eef5',
            'type': 'multipart'
        }]
        self.init_config(parts=parts)

        self.rpc_client.show_software_config.return_value = {
            'config': multipart
        }

        result = self.config.get_message()

        self.assertEqual(
            '1e0e5a60-2843-4cfd-9137-d90bdf18eef5',
            self.rpc_client.show_software_config.call_args[0][1])

        message = email.message_from_string(result)
        self.assertTrue(message.is_multipart())
        subs = message.get_payload()
        self.assertEqual(1, len(subs))
        self.assertEqual('#!/bin/bash', subs[0].get_payload())
        self.assertEqual('/opt/stack/configure.d/55-heat-config',
                         subs[0].get_filename())

    def test_get_message_multi_part_bad_format(self):
        parts = [
            {'config': '1e0e5a60-2843-4cfd-9137-d90bdf18eef5',
             'type': 'multipart'},
            {'config': '9cab10ef-16ce-4be9-8b25-a67b7313eddb',
             'type': 'text'}]
        self.init_config(parts=parts)
        self.rpc_client.show_software_config.return_value = {
            'config': '#!/bin/bash'
        }
        result = self.config.get_message()

        self.assertEqual(
            '1e0e5a60-2843-4cfd-9137-d90bdf18eef5',
            self.rpc_client.show_software_config.call_args_list[0][0][1])
        self.assertEqual(
            '9cab10ef-16ce-4be9-8b25-a67b7313eddb',
            self.rpc_client.show_software_config.call_args_list[1][0][1])

        message = email.message_from_string(result)
        self.assertTrue(message.is_multipart())
        subs = message.get_payload()
        self.assertEqual(1, len(subs))
        self.assertEqual('#!/bin/bash', subs[0].get_payload())
