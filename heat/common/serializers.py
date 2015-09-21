#
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2013 IBM Corp.
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

"""Utility methods for serializing responses."""

import datetime

from lxml import etree
from oslo_log import log as logging
from oslo_serialization import jsonutils
import six

LOG = logging.getLogger(__name__)


class JSONResponseSerializer(object):

    def to_json(self, data):
        def sanitizer(obj):
            if isinstance(obj, datetime.datetime):
                return obj.isoformat()
            return six.text_type(obj)

        response = jsonutils.dumps(data, default=sanitizer)
        LOG.debug("JSON response : %s" % response)
        return response

    def default(self, response, result):
        response.content_type = 'application/json'
        response.body = six.b(self.to_json(result))


# Escape XML serialization for these keys, as the AWS API defines them as
# JSON inside XML when the response format is XML.
JSON_ONLY_KEYS = ('TemplateBody', 'Metadata')


class XMLResponseSerializer(object):

    def object_to_element(self, obj, element):
        if isinstance(obj, list):
            for item in obj:
                subelement = etree.SubElement(element, "member")
                self.object_to_element(item, subelement)
        elif isinstance(obj, dict):
            for key, value in obj.items():
                subelement = etree.SubElement(element, key)
                if key in JSON_ONLY_KEYS:
                    if value:
                        # Need to use json.dumps for the JSON inside XML
                        # otherwise quotes get mangled and json.loads breaks
                        try:
                            subelement.text = jsonutils.dumps(value)
                        except TypeError:
                            subelement.text = str(value)
                else:
                    self.object_to_element(value, subelement)
        else:
            element.text = six.text_type(obj)

    def to_xml(self, data):
        # Assumption : root node is dict with single key
        root = next(six.iterkeys(data))
        eltree = etree.Element(root)
        self.object_to_element(data.get(root), eltree)
        response = etree.tostring(eltree)
        return response

    def default(self, response, result):
        response.content_type = 'application/xml'
        response.body = self.to_xml(result)
