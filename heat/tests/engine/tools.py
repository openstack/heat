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

import six

from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import keystone
from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine.resources.aws.ec2 import instance as instances
from heat.engine import stack as parser
from heat.engine import template as templatem
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils

wp_template = u'''
heat_template_version: 2014-10-16
description: WordPress
parameters:
  KeyName:
    description: KeyName
    type: string
    default: test\u2042
resources:
  WebServer:
    type: AWS::EC2::Instance
    properties:
      ImageId: F17-x86_64-gold
      InstanceType: m1.large
      KeyName: test
      UserData: wordpress
'''

string_template_five = '''
heat_template_version: 2013-05-23
description: Random String templates

parameters:
    salt:
        type: string
        default: "quickbrownfox"

resources:
    A:
        type: OS::Heat::RandomString
        properties:
            salt: {get_param: salt}

    B:
        type: OS::Heat::RandomString
        properties:
            salt: {get_param: salt}

    C:
        type: OS::Heat::RandomString
        depends_on: [A, B]
        properties:
            salt: {get_attr: [A, value]}

    D:
        type: OS::Heat::RandomString
        depends_on: C
        properties:
            salt: {get_param: salt}

    E:
        type: OS::Heat::RandomString
        depends_on: C
        properties:
            salt: {get_param: salt}
'''

string_template_five_update = '''
heat_template_version: 2013-05-23
description: Random String templates

parameters:
    salt:
        type: string
        default: "quickbrownfox123"

resources:
    A:
        type: OS::Heat::RandomString
        properties:
            salt: {get_param: salt}

    B:
        type: OS::Heat::RandomString
        properties:
            salt: {get_param: salt}

    F:
        type: OS::Heat::RandomString
        depends_on: [A, B]
        properties:
            salt: {get_param: salt}

    G:
        type: OS::Heat::RandomString
        depends_on: F
        properties:
            salt: {get_param: salt}

    H:
        type: OS::Heat::RandomString
        depends_on: F
        properties:
            salt: {get_param: salt}
'''

attr_cache_template = '''
heat_template_version: 2016-04-08
resources:
    A:
        type: ResourceWithComplexAttributesType
    B:
        type: OS::Heat::RandomString
        properties:
            salt: {get_attr: [A, flat_dict, key2]}
    C:
        type: OS::Heat::RandomString
        depends_on: [A, B]
        properties:
            salt: {get_attr: [A, nested_dict, dict, a]}
    D:
        type: OS::Heat::RandomString
        depends_on: C
        properties:
            salt: {get_attr: [A, nested_dict, dict, b]}
    E:
        type: OS::Heat::RandomString
        depends_on: C
        properties:
            salt: {get_attr: [A, flat_dict, key3]}
'''


def get_stack(stack_name, ctx, template=None, with_params=True,
              convergence=False, **kwargs):
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
    stack = parser.Stack(ctx, stack_name, tmpl, convergence=convergence,
                         **kwargs)
    stack.thread_group_mgr = DummyThreadGroupManager()
    return stack


def setup_keystone_mocks_with_mock(test_case, stack):
    fkc = fake_ks.FakeKeystoneClient()

    test_case.patchobject(keystone.KeystoneClientPlugin, '_create')
    keystone.KeystoneClientPlugin._create.return_value = fkc


def setup_mock_for_image_constraint_with_mock(test_case, imageId_input,
                                              imageId_output=744):
    test_case.patchobject(glance.GlanceClientPlugin,
                          'find_image_by_name_or_id',
                          return_value=imageId_output)


def validate_setup_mocks_with_mock(stack, fc, mock_image_constraint=True,
                                   validate_create=True):
    instance = stack['WebServer']
    metadata = instance.metadata_get()
    if mock_image_constraint:
        m_image = glance.GlanceClientPlugin.find_image_by_name_or_id
        m_image.assert_called_with(
            instance.properties['ImageId'])

    user_data = instance.properties['UserData']
    server_userdata = instance.client_plugin().build_userdata(
        metadata, user_data, 'ec2-user')
    nova.NovaClientPlugin.build_userdata.assert_called_with(
        metadata, user_data, 'ec2-user')

    if not validate_create:
        return

    fc.servers.create.assert_called_once_with(
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
        block_device_mapping=None)


def setup_mocks_with_mock(testcase, stack, mock_image_constraint=True,
                          mock_keystone=True):
    fc = fakes_nova.FakeClient()
    testcase.patchobject(instances.Instance, 'client', return_value=fc)
    testcase.patchobject(nova.NovaClientPlugin, 'client', return_value=fc)
    instance = stack['WebServer']
    metadata = instance.metadata_get()
    if mock_image_constraint:
        setup_mock_for_image_constraint_with_mock(
            testcase, instance.properties['ImageId'])

    if mock_keystone:
        setup_keystone_mocks_with_mock(testcase, stack)

    user_data = instance.properties['UserData']
    server_userdata = instance.client_plugin().build_userdata(
        metadata, user_data, 'ec2-user')
    testcase.patchobject(nova.NovaClientPlugin, 'build_userdata',
                         return_value=server_userdata)

    testcase.patchobject(fc.servers, 'create')

    fc.servers.create.return_value = fc.servers.list()[4]
    return fc


def setup_stack_with_mock(test_case, stack_name, ctx, create_res=True,
                          convergence=False):
    stack = get_stack(stack_name, ctx, convergence=convergence)
    stack.store()
    if create_res:
        fc = setup_mocks_with_mock(test_case, stack)
        stack.create()
        stack._persist_state()
        validate_setup_mocks_with_mock(stack, fc)
    return stack


def clean_up_stack(test_case, stack, delete_res=True):
    if delete_res:
        fc = fakes_nova.FakeClient()
        test_case.patchobject(instances.Instance, 'client', return_value=fc)
        test_case.patchobject(fc.servers, 'delete',
                              side_effect=fakes_nova.fake_exception())
    stack.delete()


def stack_context(stack_name, create_res=True, convergence=False):
    """Decorator for creating and deleting stack.

    Decorator which creates a stack by using the test case's context and
    deletes it afterwards to ensure tests clean up their stacks regardless
    of test success/failure.
    """
    def stack_delete(test_fn):
        @six.wraps(test_fn)
        def wrapped_test(test_case, *args, **kwargs):
            def create_stack():
                ctx = getattr(test_case, 'ctx', None)
                if ctx is not None:
                    stack = setup_stack_with_mock(test_case, stack_name, ctx,
                                                  create_res, convergence)
                    setattr(test_case, 'stack', stack)

            def delete_stack():
                stack = getattr(test_case, 'stack', None)
                if stack is not None and stack.id is not None:
                    clean_up_stack(test_case, stack, delete_res=create_res)

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

    def add_thread(self, callback, cnxt, trace, func, *args, **kwargs):
        # callback here is _start_with_trace(); func is the 'real' callback
        self.threads.append(func)
        return DummyThread()

    def stop(self, graceful=False):
        pass

    def wait(self):
        pass


class DummyThreadGroupManager(object):
    def __init__(self):
        self.msg_queues = []
        self.messages = []

    def start(self, stack, func, *args, **kwargs):
        # Just run the function, so we know it's completed in the test
        func(*args, **kwargs)
        return DummyThread()

    def start_with_lock(self, cnxt, stack, engine_id, func, *args, **kwargs):
        # Just run the function, so we know it's completed in the test
        func(*args, **kwargs)
        return DummyThread()

    def start_with_acquired_lock(self, stack, lock, func, *args, **kwargs):
        # Just run the function, so we know it's completed in the test
        func(*args, **kwargs)
        return DummyThread()

    def send(self, stack_id, message):
        self.messages.append(message)

    def add_msg_queue(self, stack_id, msg_queue):
        self.msg_queues.append(msg_queue)

    def remove_msg_queue(self, gt, stack_id, msg_queue):
        for q in self.msg_queues.pop(stack_id, []):
            if q is not msg_queue:
                self.add_event(stack_id, q)


class DummyThreadGroupMgrLogStart(DummyThreadGroupManager):
    def __init__(self):
        super(DummyThreadGroupMgrLogStart, self).__init__()
        self.started = []

    def start_with_lock(self, cnxt, stack, engine_id, func, *args, **kwargs):
        self.started.append((stack.id, func))
        return DummyThread()

    def start_with_acquired_lock(self, stack, lock, func, *args, **kwargs):
        self.started.append((stack.id, func))
        return DummyThread()

    def start(self, stack_id, func, *args, **kwargs):
        # Here we only store the started task so it can be checked
        self.started.append((stack_id, func))
