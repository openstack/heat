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

import webob

from heat.api.middleware import version_negotiation as vn
from heat.tests import common


class VersionController(object):
    pass


class VersionNegotiationMiddlewareTest(common.HeatTestCase):
    def _version_controller_factory(self, conf):
        return VersionController()

    def test_match_version_string(self):
        version_negotiation = vn.VersionNegotiationFilter(
            self._version_controller_factory, None, None)
        request = webob.Request({})
        major_version = 1
        minor_version = 0

        match = version_negotiation._match_version_string(
            'v{0}.{1}'.format(major_version, minor_version), request)
        self.assertTrue(match)
        self.assertEqual(major_version, request.environ['api.major_version'])
        self.assertEqual(minor_version, request.environ['api.minor_version'])

    def test_not_match_version_string(self):
        version_negotiation = vn.VersionNegotiationFilter(
            self._version_controller_factory, None, None)
        request = webob.Request({})

        match = version_negotiation._match_version_string("invalid", request)
        self.assertFalse(match)

    def test_return_version_controller_when_request_path_is_version(self):
        version_negotiation = vn.VersionNegotiationFilter(
            self._version_controller_factory, None, None)
        request = webob.Request({'PATH_INFO': 'versions'})

        response = version_negotiation.process_request(request)

        self.assertIsInstance(response, VersionController)

    def test_return_version_controller_when_request_path_is_empty(self):
        version_negotiation = vn.VersionNegotiationFilter(
            self._version_controller_factory, None, None)
        request = webob.Request({'PATH_INFO': '/'})

        response = version_negotiation.process_request(request)

        self.assertIsInstance(response, VersionController)

    def test_request_path_contains_valid_version(self):
        version_negotiation = vn.VersionNegotiationFilter(
            self._version_controller_factory, None, None)
        major_version = 1
        minor_version = 0
        request = webob.Request({'PATH_INFO':
                                 'v{0}.{1}/resource'.format(major_version,
                                                            minor_version)})

        response = version_negotiation.process_request(request)

        self.assertIsNone(response)
        self.assertEqual(major_version, request.environ['api.major_version'])
        self.assertEqual(minor_version, request.environ['api.minor_version'])

    def test_removes_version_from_request_path(self):
        version_negotiation = vn.VersionNegotiationFilter(
            self._version_controller_factory, None, None)
        expected_path = 'resource'
        request = webob.Request({'PATH_INFO': 'v1.0/{0}'.format(expected_path)
                                 })

        response = version_negotiation.process_request(request)

        self.assertIsNone(response)
        self.assertEqual(expected_path, request.path_info_peek())

    def test_request_path_contains_unknown_version(self):
        version_negotiation = vn.VersionNegotiationFilter(
            self._version_controller_factory, None, None)
        request = webob.Request({'PATH_INFO': 'v2.0/resource'})

        response = version_negotiation.process_request(request)

        self.assertIsInstance(response, VersionController)

    def test_accept_header_contains_valid_version(self):
        version_negotiation = vn.VersionNegotiationFilter(
            self._version_controller_factory, None, None)
        major_version = 1
        minor_version = 0
        request = webob.Request({'PATH_INFO': 'resource'})
        request.headers['Accept'] = (
            'application/vnd.openstack.orchestration-v{0}.{1}'.format(
                major_version, minor_version))

        response = version_negotiation.process_request(request)

        self.assertIsNone(response)
        self.assertEqual(major_version, request.environ['api.major_version'])
        self.assertEqual(minor_version, request.environ['api.minor_version'])

    def test_accept_header_contains_unknown_version(self):
        version_negotiation = vn.VersionNegotiationFilter(
            self._version_controller_factory, None, None)
        request = webob.Request({'PATH_INFO': 'resource'})
        request.headers['Accept'] = (
            'application/vnd.openstack.orchestration-v2.0')

        response = version_negotiation.process_request(request)

        self.assertIsInstance(response, VersionController)

    def test_no_URI_version_accept_header_contains_invalid_MIME_type(self):
        version_negotiation = vn.VersionNegotiationFilter(
            self._version_controller_factory, None, None)
        request = webob.Request({'PATH_INFO': 'resource'})
        request.headers['Accept'] = 'application/invalidMIMEType'

        response = version_negotiation.process_request(request)

        self.assertIsInstance(response, webob.exc.HTTPNotFound)

    def test_invalid_utf8_path(self):
        version_negotiation = vn.VersionNegotiationFilter(
            self._version_controller_factory, None, None)
        request = webob.Request.blank('/%c0')

        response = version_negotiation.process_request(request)

        self.assertIsInstance(response, webob.exc.HTTPBadRequest)
