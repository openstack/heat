# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Red Hat, Inc.
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

import json
import unittest

from heat.engine.json2capexml import *

class ParseTestCase(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_01(self):
        done=False

        with open('templates/WordPress_Single_Instance.template') as f:
            blob = json.load(f)
            cape_transformer = Json2CapeXml(blob, 'WordPress_Single_Instance')
            cape_transformer.convert()
            print cape_transformer.get_xml()
            done=True

        self.assertTrue(done)

