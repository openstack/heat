#
# Copyright 2010-2011 OpenStack Foundation
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

import datetime

import webob

from heat.common import serializers
from heat.tests.common import HeatTestCase


class JSONResponseSerializerTest(HeatTestCase):

    def test_to_json(self):
        fixture = {"key": "value"}
        expected = '{"key": "value"}'
        actual = serializers.JSONResponseSerializer().to_json(fixture)
        self.assertEqual(expected, actual)

    def test_to_json_with_date_format_value(self):
        fixture = {"date": datetime.datetime(1, 3, 8, 2)}
        expected = '{"date": "0001-03-08T02:00:00"}'
        actual = serializers.JSONResponseSerializer().to_json(fixture)
        self.assertEqual(expected, actual)

    def test_to_json_with_more_deep_format(self):
        fixture = {"is_public": True, "name": [{"name1": "test"}]}
        expected = '{"is_public": true, "name": [{"name1": "test"}]}'
        actual = serializers.JSONResponseSerializer().to_json(fixture)
        self.assertEqual(expected, actual)

    def test_default(self):
        fixture = {"key": "value"}
        response = webob.Response()
        serializers.JSONResponseSerializer().default(response, fixture)
        self.assertEqual(200, response.status_int)
        content_types = filter(lambda h: h[0] == 'Content-Type',
                               response.headerlist)
        self.assertEqual(1, len(content_types))
        self.assertEqual('application/json', response.content_type)
        self.assertEqual('{"key": "value"}', response.body)


class XMLResponseSerializerTest(HeatTestCase):

    def test_to_xml(self):
        fixture = {"key": "value"}
        expected = '<key>value</key>'
        actual = serializers.XMLResponseSerializer().to_xml(fixture)
        self.assertEqual(expected, actual)

    def test_to_xml_with_date_format_value(self):
        fixture = {"date": datetime.datetime(1, 3, 8, 2)}
        expected = '<date>0001-03-08 02:00:00</date>'
        actual = serializers.XMLResponseSerializer().to_xml(fixture)
        self.assertEqual(expected, actual)

    def test_to_xml_with_list(self):
        fixture = {"name": ["1", "2"]}
        expected = '<name><member>1</member><member>2</member></name>'
        actual = serializers.XMLResponseSerializer().to_xml(fixture)
        self.assertEqual(expected, actual)

    def test_to_xml_with_more_deep_format(self):
        # Note we expect tree traversal from one root key, which is compatible
        # with the AWS format responses we need to serialize
        fixture = {"aresponse":
                   {"is_public": True, "name": [{"name1": "test"}]}}
        expected = ('<aresponse><is_public>True</is_public>'
                    '<name><member><name1>test</name1></member></name>'
                    '</aresponse>')
        actual = serializers.XMLResponseSerializer().to_xml(fixture)
        self.assertEqual(expected, actual)

    def test_to_xml_with_json_only_keys(self):
        # Certain keys are excluded from serialization because CFN
        # format demands a json blob in the XML body
        fixture = {"aresponse":
                   {"is_public": True,
                    "TemplateBody": {"name1": "test"},
                    "Metadata": {"name2": "test2"}}}
        expected = ('<aresponse><is_public>True</is_public>'
                    '<TemplateBody>{"name1": "test"}</TemplateBody>'
                    '<Metadata>{"name2": "test2"}</Metadata></aresponse>')
        actual = serializers.XMLResponseSerializer().to_xml(fixture)
        self.assertEqual(expected, actual)

    def test_default(self):
        fixture = {"key": "value"}
        response = webob.Response()
        serializers.XMLResponseSerializer().default(response, fixture)
        self.assertEqual(200, response.status_int)
        content_types = filter(lambda h: h[0] == 'Content-Type',
                               response.headerlist)
        self.assertEqual(1, len(content_types))
        self.assertEqual('application/xml', response.content_type)
        self.assertEqual('<key>value</key>', response.body)
