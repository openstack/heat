# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import sys

import mox
import six

from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import keystone
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine.resources.aws.ec2 import instance as instances
from heat.engine import stack as parser
from heat.engine import template as templatem
from heat.tests import fakes as test_fakes
from heat.tests.nova import fakes as fakes_nova
from heat.tests import utils

wp_template = '''
heat_template_version: 2014-10-16
description: WordPress
parameters:
  KeyName:
    description: KeyName
    type: string
    default: test
resources:
  WebServer:
    type: AWS::EC2::Instance
    properties:
      ImageId: F17-x86_64-gold
      InstanceType: m1.large
      KeyName: test
      UserData: wordpress
'''


def get_stack(stack_name, ctx, template=None, with_params=True,
              convergence=False):
    if template is None:
        t = template_format.parse(wp_template)
        if with_params:
            env = environment.Environment({'KeyName': 'test'})
            tmpl = templatem.Template(t, env=env)
        else:
            tmpl = templatem.Template(t)
    else:
        t = template_format.parse(template)
        tmpl = templatem.Template(t)
    stack = parser.Stack(ctx, stack_name, tmpl, convergence=convergence)
    return stack


def setup_keystone_mocks(mocks, stack):
    fkc = test_fakes.FakeKeystoneClient()

    mocks.StubOutWithMock(keystone.KeystoneClientPlugin, '_create')
    keystone.KeystoneClientPlugin._create().AndReturn(fkc)


def setup_mock_for_image_constraint(mocks, imageId_input,
                                    imageId_output=744):
    mocks.StubOutWithMock(glance.GlanceClientPlugin, 'get_image_id')
    glance.GlanceClientPlugin.get_image_id(
        imageId_input).MultipleTimes().AndReturn(imageId_output)


def setup_mocks(mocks, stack, mock_image_constraint=True,
                mock_keystone=True):
    fc = fakes_nova.FakeClient()
    mocks.StubOutWithMock(instances.Instance, 'nova')
    instances.Instance.nova().MultipleTimes().AndReturn(fc)
    mocks.StubOutWithMock(nova.NovaClientPlugin, '_create')
    nova.NovaClientPlugin._create().AndReturn(fc)
    instance = stack['WebServer']
    metadata = instance.metadata_get()
    if mock_image_constraint:
        setup_mock_for_image_constraint(mocks,
                                        instance.t['Properties']['ImageId'])

    if mock_keystone:
        setup_keystone_mocks(mocks, stack)

    user_data = instance.properties['UserData']
    server_userdata = instance.client_plugin().build_userdata(
        metadata, user_data, 'ec2-user')
    mocks.StubOutWithMock(nova.NovaClientPlugin, 'build_userdata')
    nova.NovaClientPlugin.build_userdata(
        metadata,
        instance.t['Properties']['UserData'],
        'ec2-user').AndReturn(server_userdata)

    mocks.StubOutWithMock(fc.servers, 'create')
    fc.servers.create(
        image=744,
        flavor=3,
        key_name='test',
        name=utils.PhysName(stack.name, 'WebServer'),
        security_groups=None,
        userdata=server_userdata,
        scheduler_hints=None,
        meta=None,
        nics=None,
        availability_zone=None,
        block_device_mapping=None).AndReturn(fc.servers.list()[4])
    return fc


def setup_stack(stack_name, ctx, create_res=True):
    stack = get_stack(stack_name, ctx)
    stack.store()
    if create_res:
        m = mox.Mox()
        setup_mocks(m, stack)
        m.ReplayAll()
        stack.create()
        m.UnsetStubs()
    return stack


def clean_up_stack(stack, delete_res=True):
    if delete_res:
        m = mox.Mox()
        fc = fakes_nova.FakeClient()
        m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().MultipleTimes().AndReturn(fc)
        m.StubOutWithMock(fc.client, 'get_servers_9999')
        get = fc.client.get_servers_9999
        get().AndRaise(fakes_nova.fake_exception())
        m.ReplayAll()
    stack.delete()
    if delete_res:
        m.UnsetStubs()


def stack_context(stack_name, create_res=True):
    """
    Decorator which creates a stack by using the test case's context and
    deletes it afterwards to ensure tests clean up their stacks regardless
    of test success/failure
    """
    def stack_delete(test_fn):
        @six.wraps(test_fn)
        def wrapped_test(test_case, *args, **kwargs):
            def create_stack():
                ctx = getattr(test_case, 'ctx', None)
                if ctx is not None:
                    stack = setup_stack(stack_name, ctx, create_res)
                    setattr(test_case, 'stack', stack)

            def delete_stack():
                stack = getattr(test_case, 'stack', None)
                if stack is not None and stack.id is not None:
                    clean_up_stack(stack, delete_res=create_res)

            create_stack()
            try:
                test_fn(test_case, *args, **kwargs)
            except Exception:
                exc_class, exc_val, exc_tb = sys.exc_info()
                try:
                    delete_stack()
                finally:
                    six.reraise(exc_class, exc_val, exc_tb)
            else:
                delete_stack()

        return wrapped_test
    return stack_delete


class DummyThread(object):

    def link(self, callback, *args):
        pass


class DummyThreadGroup(object):
    def __init__(self):
        self.threads = []

    def add_timer(self, interval, callback, initial_delay=None,
                  *args, **kwargs):
        self.threads.append(callback)

    def stop_timers(self):
        pass

    def add_thread(self, callback, *args, **kwargs):
        # just to make _start_with_trace() easier to test:
        # callback == _start_with_trace
        # args[0] == trace_info
        # args[1] == actual_callback
        callback = args[1]
        self.threads.append(callback)
        return DummyThread()

    def stop(self, graceful=False):
        pass

    def wait(self):
        pass
