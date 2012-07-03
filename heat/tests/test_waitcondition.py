from datetime import datetime
import eventlet
import json
import logging
import os
import sys

import nose
import unittest
import mox
from nose.plugins.attrib import attr
from nose import with_setup

import heat.db as db_api
from heat.engine import parser

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
        self.greenpool = eventlet.GreenPool()

    def tearDown(self):
        self.m.UnsetStubs()

    def create_stack(self, stack_name, temp, params):
        stack = parser.Stack(None, stack_name, temp, 0, params)

        rt = {}
        rt['template'] = temp
        rt['StackName'] = stack_name
        new_rt = db_api.raw_template_create(None, rt)

        ct = {'username': 'fred',
              'password': 'mentions_fruit'}
        new_creds = db_api.user_creds_create(ct)

        s = {}
        s['name'] = stack_name
        s['raw_template_id'] = new_rt.id
        s['user_creds_id'] = new_creds.id
        s['username'] = ct['username']
        new_s = db_api.stack_create(None, s)
        stack.id = new_s.id
        pt = {}
        pt['template'] = stack.t
        pt['raw_template_id'] = new_rt.id
        new_pt = db_api.parsed_template_create(None, pt)

        stack.parsed_template_id = new_pt.id
        return stack

    def test_post_success_to_handle(self):
        params = {}
        t = json.loads(test_template_waitcondition)
        stack = self.create_stack('test_stack', t, params)

        self.m.ReplayAll()
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
