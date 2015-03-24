#
# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
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


import fixtures
import six

from heat.common import exception
from heat.common.i18n import _
from heat.tests import common


class TestException(exception.HeatException):
    msg_fmt = _("Testing message %(text)s")


class TestHeatException(common.HeatTestCase):

    def test_fatal_exception_error(self):
        self.useFixture(fixtures.MonkeyPatch(
            'heat.common.exception._FATAL_EXCEPTION_FORMAT_ERRORS',
            True))
        self.assertRaises(KeyError, TestException)

    def test_format_string_error_message(self):
        message = "This format %(message)s should work"
        err = exception.Error(message)
        self.assertEqual(message, six.text_type(err))


class TestStackValidationFailed(common.HeatTestCase):

    scenarios = [
        ('test_full_exception', dict(
            kwargs=dict(
                error='Error',
                path=['some', 'path'],
                message='Some message'),
            expected='Error : some.path: Some message',
            called_error='Error',
            called_path=['some', 'path'],
            called_msg='Some message'
        )),
        ('test_no_error_exception', dict(
            kwargs=dict(
                path=['some', 'path'],
                message='Chain letter'),
            expected='some.path: Chain letter',
            called_error='',
            called_path=['some', 'path'],
            called_msg='Chain letter'
        )),
        ('test_no_path_exception', dict(
            kwargs=dict(
                error='Error',
                message='Just no.'),
            expected='Error : Just no.',
            called_error='Error',
            called_path=[],
            called_msg='Just no.'
        )),
        ('test_no_msg_exception', dict(
            kwargs=dict(
                error='Error',
                path=['we', 'lost', 'our', 'message']),
            expected='Error : we.lost.our.message: ',
            called_error='Error',
            called_path=['we', 'lost', 'our', 'message'],
            called_msg=''
        )),
        ('test_old_format_exception', dict(
            kwargs=dict(
                message='Wow. I think I am old error message format.'
            ),
            expected='Wow. I think I am old error message format.',
            called_error='',
            called_path=[],
            called_msg='Wow. I think I am old error message format.'
        )),
        ('test_int_path_item_exception', dict(
            kwargs=dict(
                path=['null', 0]
            ),
            expected='null[0]: ',
            called_error='',
            called_path=['null', 0],
            called_msg=''
        )),
        ('test_digit_path_item_exception', dict(
            kwargs=dict(
                path=['null', '0']
            ),
            expected='null[0]: ',
            called_error='',
            called_path=['null', '0'],
            called_msg=''
        )),
        ('test_string_path_exception', dict(
            kwargs=dict(
                path='null[0].not_null'
            ),
            expected='null[0].not_null: ',
            called_error='',
            called_path=['null[0].not_null'],
            called_msg=''
        ))
    ]

    def test_exception(self):
        try:
            raise exception.StackValidationFailed(**self.kwargs)
        except exception.StackValidationFailed as ex:
            self.assertEqual(self.expected, six.text_type(ex))
            self.assertEqual(self.called_error, ex.error)
            self.assertEqual(self.called_path, ex.path)
            self.assertEqual(self.called_msg, ex.error_message)
