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

import collections
import datetime

from lxml import etree
from oslo_serialization import jsonutils as json
import six
import webob

from heat.common import serializers
from heat.tests import common


class JSONResponseSerializerTest(common.HeatTestCase):

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
        fixture = collections.OrderedDict([
            ('is_public', True),
            ('name', [collections.OrderedDict([
                ('name1', 'test'),
            ])])
        ])
        expected = '{"is_public": true, "name": [{"name1": "test"}]}'
        actual = serializers.JSONResponseSerializer().to_json(fixture)
        self.assertEqual(json.loads(expected), json.loads(actual))

    def test_to_json_with_objects(self):
        fixture = collections.OrderedDict([
            ('is_public', True),
            ('value', complex(1, 2)),
        ])
        expected = '{"is_public": true, "value": "(1+2j)"}'
        actual = serializers.JSONResponseSerializer().to_json(fixture)
        self.assertEqual(json.loads(expected), json.loads(actual))

    def test_default(self):
        fixture = {"key": "value"}
        response = webob.Response()
        serializers.JSONResponseSerializer().default(response, fixture)
        self.assertEqual(200, response.status_int)
        content_types = list(filter(lambda h: h[0] == 'Content-Type',
                                    response.headerlist))
        self.assertEqual(1, len(content_types))
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(b'{"key": "value"}', response.body)


class XMLResponseSerializerTest(common.HeatTestCase):

    def _recursive_dict(self, element):
        return element.tag, dict(
            map(self._recursive_dict, element)) or element.text

    def test_to_xml(self):
        fixture = {"key": "value"}
        expected = b'<key>value</key>'
        actual = serializers.XMLResponseSerializer().to_xml(fixture)
        self.assertEqual(expected, actual)

    def test_to_xml_with_date_format_value(self):
        fixture = {"date": datetime.datetime(1, 3, 8, 2)}
        expected = b'<date>0001-03-08 02:00:00</date>'
        actual = serializers.XMLResponseSerializer().to_xml(fixture)
        self.assertEqual(expected, actual)

    def test_to_xml_with_list(self):
        fixture = {"name": ["1", "2"]}
        expected = b'<name><member>1</member><member>2</member></name>'
        actual = serializers.XMLResponseSerializer().to_xml(fixture)
        actual_xml_tree = etree.XML(actual)
        actual_xml_dict = self._recursive_dict(actual_xml_tree)
        expected_xml_tree = etree.XML(expected)
        expected_xml_dict = self._recursive_dict(expected_xml_tree)
        self.assertEqual(expected_xml_dict, actual_xml_dict)

    def test_to_xml_with_more_deep_format(self):
        # Note we expect tree traversal from one root key, which is compatible
        # with the AWS format responses we need to serialize
        fixture = collections.OrderedDict([
            ('aresponse', collections.OrderedDict([
                ('is_public', True),
                ('name', [collections.OrderedDict([
                    ('name1', 'test'),
                ])])
            ]))
        ])
        expected = six.b('<aresponse><is_public>True</is_public>'
                         '<name><member><name1>test</name1></member></name>'
                         '</aresponse>')
        actual = serializers.XMLResponseSerializer().to_xml(fixture)
        actual_xml_tree = etree.XML(actual)
        actual_xml_dict = self._recursive_dict(actual_xml_tree)
        expected_xml_tree = etree.XML(expected)
        expected_xml_dict = self._recursive_dict(expected_xml_tree)

        self.assertEqual(expected_xml_dict, actual_xml_dict)

    def test_to_xml_with_json_only_keys(self):
        # Certain keys are excluded from serialization because CFN
        # format demands a json blob in the XML body
        fixture = collections.OrderedDict([
            ('aresponse', collections.OrderedDict([
                ('is_public', True),
                ('TemplateBody', {"name1": "test"}),
                ('Metadata', {"name2": "test2"}),
            ]))
        ])
        expected = six.b('<aresponse><is_public>True</is_public>'
                         '<TemplateBody>{"name1": "test"}</TemplateBody>'
                         '<Metadata>{"name2": "test2"}</Metadata></aresponse>')
        actual = serializers.XMLResponseSerializer().to_xml(fixture)
        actual_xml_tree = etree.XML(actual)
        actual_xml_dict = self._recursive_dict(actual_xml_tree)
        expected_xml_tree = etree.XML(expected)
        expected_xml_dict = self._recursive_dict(expected_xml_tree)
        self.assertEqual(expected_xml_dict, actual_xml_dict)

    def test_default(self):
        fixture = {"key": "value"}
        response = webob.Response()
        serializers.XMLResponseSerializer().default(response, fixture)
        self.assertEqual(200, response.status_int)
        content_types = list(filter(lambda h: h[0] == 'Content-Type',
                                    response.headerlist))
        self.assertEqual(1, len(content_types))
        self.assertEqual('application/xml', response.content_type)
        self.assertEqual(b'<key>value</key>', response.body)
