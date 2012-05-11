import sys
import os

import nose
import unittest
import mox
import json
import sqlalchemy

from nose.plugins.attrib import attr
from nose import with_setup

from heat.tests.v1_1 import fakes
from heat.engine import volume as volumes
import heat.db as db_api
from heat.engine import parser


@attr(tag=['unit', 'validate'])
@attr(speed='fast')
class validateTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeClient()

    def tearDown(self):
        self.m.UnsetStubs()
        print "volumeTest teardown complete"

    def test_validate_volumeattach_valid(self):
        f = open('../../templates/WordPress_Single_Instance_With_EBS.template')
        t = json.loads(f.read())
        f.close()

        params = {}
        parameters = {}
        params['KeyStoneCreds'] = None
        t['Parameters']['KeyName']['Value'] = 'test'
        stack = parser.Stack('test_stack', t, 0, params)

        self.m.StubOutWithMock(db_api, 'resource_get_by_name_and_stack')
        db_api.resource_get_by_name_and_stack(None, 'test_resource_name',\
                                              stack).AndReturn(None)

        self.m.ReplayAll()
        volumeattach = volumes.VolumeAttachment('test_resource_name',\
                       t['Resources']['MountPoint'], stack)
        volumeattach.stack.resolve_attributes(volumeattach.t)
        volumeattach.stack.resolve_joins(volumeattach.t)
        volumeattach.stack.resolve_base64(volumeattach.t)
        assert(volumeattach.validate() == None)

    def test_validate_volumeattach_invalid(self):
        f = open('../../templates/WordPress_Single_Instance_With_EBS.template')
        t = json.loads(f.read())
        f.close()

        params = {}
        parameters = {}
        params['KeyStoneCreds'] = None
        t['Parameters']['KeyName']['Value'] = 'test'
        t['Resources']['MountPoint']['Properties']['Device'] = '/dev/sdb'
        stack = parser.Stack('test_stack', t, 0, params)

        self.m.StubOutWithMock(db_api, 'resource_get_by_name_and_stack')
        db_api.resource_get_by_name_and_stack(None, 'test_resource_name',\
                                              stack).AndReturn(None)

        self.m.ReplayAll()
        volumeattach = volumes.VolumeAttachment('test_resource_name',\
                       t['Resources']['MountPoint'], stack)
        volumeattach.stack.resolve_attributes(volumeattach.t)
        volumeattach.stack.resolve_joins(volumeattach.t)
        volumeattach.stack.resolve_base64(volumeattach.t)
        assert(volumeattach.validate)

    # allows testing of the test directly, shown below
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()
