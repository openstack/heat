
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

import errno
import mox
import os
import pkg_resources
import subprocess

from heat.cloudinit import loguserdata
from heat.tests.common import HeatTestCase


class FakeCiVersion(object):
    def __init__(self, version=None):
        self.version = version


class FakePOpen(object):
    def __init__(self, returncode=0):
        self.returncode = returncode

    def wait(self):
        pass

    def communicate(self, input=None):
        pass


class LoguserdataTest(HeatTestCase):

    def setUp(self):
        super(LoguserdataTest, self).setUp()
        self.m.StubOutWithMock(pkg_resources, 'get_distribution')
        self.m.StubOutWithMock(subprocess, 'Popen')
        self.m.StubOutWithMock(os, 'chmod')

    def test_ci_version(self):
        # too old versions
        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('0.5.0'))
        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('0.5.9'))

        # new enough versions
        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('0.6.0'))
        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('0.7.0'))
        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('1.0'))
        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('2.0'))

        self.m.ReplayAll()

        self.assertFalse(loguserdata.chk_ci_version())
        self.assertFalse(loguserdata.chk_ci_version())

        self.assertTrue(loguserdata.chk_ci_version())
        self.assertTrue(loguserdata.chk_ci_version())
        self.assertTrue(loguserdata.chk_ci_version())
        self.assertTrue(loguserdata.chk_ci_version())

        self.m.VerifyAll()

    def test_call(self):
        subprocess.Popen(
            ['echo', 'hi'],
            stderr=mox.IgnoreArg(),
            stdout=mox.IgnoreArg()).AndReturn(FakePOpen(0))

        self.m.ReplayAll()
        self.assertEqual(0, loguserdata.call(['echo', 'hi']))
        self.m.VerifyAll()

    def test_main(self):

        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('0.7.0'))

        os.chmod('/var/lib/heat-cfntools/cfn-userdata', 0o700).AndReturn(None)
        subprocess.Popen(
            ['/var/lib/heat-cfntools/cfn-userdata'],
            stderr=mox.IgnoreArg(),
            stdout=mox.IgnoreArg()).AndReturn(FakePOpen(0))

        self.m.ReplayAll()
        loguserdata.main()
        self.m.VerifyAll()

    def test_main_script_empty(self):

        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('0.7.0'))

        os.chmod('/var/lib/heat-cfntools/cfn-userdata', 0o700).AndReturn(None)
        subprocess.Popen(
            ['/var/lib/heat-cfntools/cfn-userdata'],
            stderr=mox.IgnoreArg(),
            stdout=mox.IgnoreArg()).AndRaise(
                OSError(errno.ENOEXEC, "empty script"))

        self.m.ReplayAll()
        self.assertIsNone(loguserdata.main())

        self.m.VerifyAll()

    def test_main_os_error(self):

        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('0.7.0'))

        os.chmod('/var/lib/heat-cfntools/cfn-userdata', 0o700).AndReturn(None)
        subprocess.Popen(
            ['/var/lib/heat-cfntools/cfn-userdata'],
            stderr=mox.IgnoreArg(),
            stdout=mox.IgnoreArg()).AndRaise(
                OSError(errno.ENOENT, "no such file"))

        self.m.ReplayAll()
        self.assertEqual(os.EX_OSERR, loguserdata.main())

        self.m.VerifyAll()

    def test_main_error_other(self):
        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('0.7.0'))
        os.chmod('/var/lib/heat-cfntools/cfn-userdata', 0o700).AndReturn(None)
        subprocess.Popen(
            ['/var/lib/heat-cfntools/cfn-userdata'],
            stderr=mox.IgnoreArg(),
            stdout=mox.IgnoreArg()).AndRaise(IOError("read failed"))

        self.m.ReplayAll()
        self.assertEqual(os.EX_SOFTWARE, loguserdata.main())
        self.m.VerifyAll()

    def test_main_fails(self):

        #fail on ci version
        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('0.5.0'))
        #fail on execute cfn-userdata
        pkg_resources.get_distribution('cloud-init').AndReturn(
            FakeCiVersion('0.7.0'))

        os.chmod('/var/lib/heat-cfntools/cfn-userdata', 0o700).AndReturn(None)
        subprocess.Popen(
            ['/var/lib/heat-cfntools/cfn-userdata'],
            stderr=mox.IgnoreArg(),
            stdout=mox.IgnoreArg()).AndReturn(FakePOpen(-2))

        self.m.ReplayAll()
        self.assertEqual(-1, loguserdata.main())
        self.assertEqual(-2, loguserdata.main())
        self.m.VerifyAll()
