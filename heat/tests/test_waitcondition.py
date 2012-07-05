# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


from datetime import datetime
import eventlet
import json
import logging
import os
import sys

import nose
import unittest
from nose.plugins.attrib import attr
from nose import with_setup

import heat.db as db_api
from heat.engine import parser
from heat.common import context

logger = logging.getLogger('test_waitcondition')

test_template_waitcondition = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a WaitCondition.",
  "Parameters" : {},
  "Resources" : {
    "WaitHandle" : {
      "Type" : "AWS::CloudFormation::WaitConditionHandle"
    },
    "WaitForTheHandle" : {
      "Type" : "AWS::CloudFormation::WaitCondition",
      "Properties" : {
        "Handle" : {"Ref" : "WaitHandle"},
        "Timeout" : "5"
      }
    }
  }
}
'''


@attr(tag=['unit', 'resource'])
@attr(speed='slow')
class stacksTest(unittest.TestCase):
    def setUp(self):
        self.greenpool = eventlet.GreenPool()

    def create_stack(self, stack_name, temp, params):
        template = parser.Template(temp)
        parameters = parser.Parameters(stack_name, template, params)
        stack = parser.Stack(context.get_admin_context(), stack_name,
                             template, parameters)

        stack.store()
        return stack

    def test_post_success_to_handle(self):
        params = {}
        t = json.loads(test_template_waitcondition)
        stack = self.create_stack('test_stack', t, params)

        self.greenpool.spawn_n(stack.create)
        eventlet.sleep(1)
        self.assertEqual(stack.resources['WaitForTheHandle'].state,
                         'IN_PROGRESS')

        r = db_api.resource_get_by_name_and_stack(None, 'WaitHandle',
                                                  stack.id)
        self.assertEqual(r.name, 'WaitHandle')

        metadata = {"Status": "SUCCESS",
                    "Reason": "woot toot",
                    "Data": "Application has completed configuration.",
                    "UniqueId": "00000"}

        r.update_and_save({'rsrc_metadata': metadata})

        eventlet.sleep(2)

        logger.debug('state %s' % stack.resources['WaitForTheHandle'].state)
        self.assertEqual(stack.resources['WaitForTheHandle'].state,
                         'CREATE_COMPLETE')

        self.greenpool.waitall()

    # allows testing of the test directly
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()
