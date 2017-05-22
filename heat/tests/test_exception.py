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
import mock
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
        ('test_error_as_exception', dict(
            kwargs=dict(
                error=exception.StackValidationFailed(
                    error='Error',
                    path=['some', 'path'],
                    message='Some message')),
            expected='Error: some.path: Some message',
            called_error='Error',
            called_path=['some', 'path'],
            called_msg='Some message'
        )),
        ('test_full_exception', dict(
            kwargs=dict(
                error='Error',
                path=['some', 'path'],
                message='Some message'),
            expected='Error: some.path: Some message',
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
            expected='Error: Just no.',
            called_error='Error',
            called_path=[],
            called_msg='Just no.'
        )),
        ('test_no_msg_exception', dict(
            kwargs=dict(
                error='Error',
                path=['we', 'lost', 'our', 'message']),
            expected='Error: we.lost.our.message: ',
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
            self.assertIn(self.expected, six.text_type(ex))
            self.assertIn(self.called_error, ex.error)
            self.assertEqual(self.called_path, ex.path)
            self.assertEqual(self.called_msg, ex.error_message)


class TestResourceFailure(common.HeatTestCase):
    def test_status_reason_resource(self):
        reason = ('Resource CREATE failed: ValueError: resources.oops: '
                  'Test Resource failed oops')

        exc = exception.ResourceFailure(reason, None, action='CREATE')
        self.assertEqual('ValueError', exc.error)
        self.assertEqual(['resources', 'oops'], exc.path)
        self.assertEqual('Test Resource failed oops', exc.error_message)

    def test_status_reason_general(self):
        reason = ('something strange happened')
        exc = exception.ResourceFailure(reason, None, action='CREATE')
        self.assertEqual('', exc.error)
        self.assertEqual([], exc.path)
        self.assertEqual('something strange happened', exc.error_message)

    def test_status_reason_general_res(self):
        res = mock.Mock()
        res.name = 'fred'
        res.stack.t.get_section_name.return_value = 'Resources'

        reason = ('something strange happened')
        exc = exception.ResourceFailure(reason, res, action='CREATE')
        self.assertEqual('', exc.error)
        self.assertEqual(['Resources', 'fred'], exc.path)
        self.assertEqual('something strange happened', exc.error_message)

    def test_std_exception(self):
        base_exc = ValueError('sorry mom')
        exc = exception.ResourceFailure(base_exc, None, action='UPDATE')
        self.assertEqual('ValueError', exc.error)
        self.assertEqual([], exc.path)
        self.assertEqual('sorry mom', exc.error_message)

    def test_std_exception_with_resource(self):
        base_exc = ValueError('sorry mom')
        res = mock.Mock()
        res.name = 'fred'
        res.stack.t.get_section_name.return_value = 'Resources'
        exc = exception.ResourceFailure(base_exc, res, action='UPDATE')
        self.assertEqual('ValueError', exc.error)
        self.assertEqual(['Resources', 'fred'], exc.path)
        self.assertEqual('sorry mom', exc.error_message)

    def test_heat_exception(self):
        base_exc = ValueError('sorry mom')
        heat_exc = exception.ResourceFailure(base_exc, None, action='UPDATE')
        exc = exception.ResourceFailure(heat_exc, None, action='UPDATE')
        self.assertEqual('ValueError', exc.error)
        self.assertEqual([], exc.path)
        self.assertEqual('sorry mom', exc.error_message)

    def test_nested_exceptions(self):
        res = mock.Mock()
        res.name = 'frodo'
        res.stack.t.get_section_name.return_value = 'Resources'

        reason = ('Resource UPDATE failed: ValueError: resources.oops: '
                  'Test Resource failed oops')
        base_exc = exception.ResourceFailure(reason, res, action='UPDATE')
        exc = exception.ResourceFailure(base_exc, res, action='UPDATE')
        self.assertEqual(['Resources', 'frodo', 'resources', 'oops'], exc.path)
        self.assertEqual('ValueError', exc.error)
        self.assertEqual('Test Resource failed oops', exc.error_message)
