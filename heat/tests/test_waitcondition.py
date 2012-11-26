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


import json
import logging
import mox
import sys

import eventlet
import nose
import unittest
from nose.plugins.attrib import attr

import heat.db as db_api
from heat.engine import format
from heat.engine import parser
from heat.engine.resources import wait_condition as wc
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
        self.m = mox.Mox()
        self.m.StubOutWithMock(wc.WaitCondition,
                               '_get_status_reason')
        self.m.StubOutWithMock(wc.WaitCondition,
                               '_create_timeout')
        self.m.StubOutWithMock(eventlet, 'sleep')

    def tearDown(self):
        self.m.UnsetStubs()

    def create_stack(self, stack_name, temp, params):
        template = parser.Template(temp)
        parameters = parser.Parameters(stack_name, template, params)
        stack = parser.Stack(context.get_admin_context(), stack_name,
                             template, parameters)

        stack.store()
        return stack

    def test_post_success_to_handle(self):

        t = format.parse_to_template(test_template_waitcondition)
        stack = self.create_stack('test_stack', t, {})

        wc.WaitCondition._create_timeout().AndReturn(eventlet.Timeout(5))
        wc.WaitCondition._get_status_reason(
                         mox.IgnoreArg()).AndReturn(('WAITING', ''))
        eventlet.sleep(1).AndReturn(None)
        wc.WaitCondition._get_status_reason(
                         mox.IgnoreArg()).AndReturn(('WAITING', ''))
        eventlet.sleep(1).AndReturn(None)
        wc.WaitCondition._get_status_reason(
                         mox.IgnoreArg()).AndReturn(('SUCCESS', 'woot toot'))

        self.m.ReplayAll()

        stack.create()

        resource = stack.resources['WaitForTheHandle']
        self.assertEqual(resource.state,
                         'CREATE_COMPLETE')

        r = db_api.resource_get_by_name_and_stack(None, 'WaitHandle',
                                                  stack.id)
        self.assertEqual(r.name, 'WaitHandle')

        self.m.VerifyAll()

    def test_timeout(self):

        t = format.parse_to_template(test_template_waitcondition)
        stack = self.create_stack('test_stack', t, {})

        tmo = eventlet.Timeout(6)
        wc.WaitCondition._create_timeout().AndReturn(tmo)
        wc.WaitCondition._get_status_reason(
                         mox.IgnoreArg()).AndReturn(('WAITING', ''))
        eventlet.sleep(1).AndReturn(None)
        wc.WaitCondition._get_status_reason(
                         mox.IgnoreArg()).AndReturn(('WAITING', ''))
        eventlet.sleep(1).AndRaise(tmo)

        self.m.ReplayAll()

        stack.create()

        resource = stack.resources['WaitForTheHandle']

        self.assertEqual(resource.state,
                         'CREATE_FAILED')
        self.assertEqual(wc.WaitCondition.UPDATE_REPLACE,
                  resource.handle_update())

        stack.delete()

        self.m.VerifyAll()

    # allows testing of the test directly
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()
