# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Red Hat, Inc.
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

"""
Unit Tests for heat.rpc.client
"""


from oslo.config import cfg
import stubout
import testtools

from heat.common import config
from heat.common import context
from heat.common import identifier
from heat.rpc import api as rpc_api
from heat.rpc import client as rpc_client
from heat.openstack.common import rpc


class EngineRpcAPITestCase(testtools.TestCase):

    def setUp(self):
        config.register_engine_opts()
        self.context = context.get_admin_context()
        cfg.CONF.set_default('rpc_backend',
                             'heat.openstack.common.rpc.impl_fake')
        cfg.CONF.set_default('verbose', True)
        cfg.CONF.set_default('host', 'host')

        self.stubs = stubout.StubOutForTesting()
        self.identity = dict(identifier.HeatIdentifier('engine_test_tenant',
                                                       '6',
                                                       'wordpress'))
        super(EngineRpcAPITestCase, self).setUp()

    def _test_engine_api(self, method, rpc_method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        if 'rpcapi_class' in kwargs:
            rpcapi_class = kwargs['rpcapi_class']
            del kwargs['rpcapi_class']
        else:
            rpcapi_class = rpc_client.EngineClient
        rpcapi = rpcapi_class()
        expected_retval = 'foo' if method == 'call' else None

        expected_version = kwargs.pop('version', rpcapi.BASE_RPC_API_VERSION)
        expected_msg = rpcapi.make_msg(method, **kwargs)

        expected_msg['version'] = expected_version
        expected_topic = rpc_api.ENGINE_TOPIC

        cast_and_call = ['delete_stack']
        if rpc_method == 'call' and method in cast_and_call:
            kwargs['cast'] = False

        self.fake_args = None
        self.fake_kwargs = None

        def _fake_rpc_method(*args, **kwargs):
            self.fake_args = args
            self.fake_kwargs = kwargs
            if expected_retval:
                return expected_retval

        self.stubs.Set(rpc, rpc_method, _fake_rpc_method)

        retval = getattr(rpcapi, method)(ctxt, **kwargs)

        self.assertEqual(retval, expected_retval)
        expected_args = [ctxt, expected_topic, expected_msg]
        for arg, expected_arg in zip(self.fake_args, expected_args):
            self.assertEqual(arg, expected_arg)

    def test_show_stack(self):
        self._test_engine_api('show_stack', 'call', stack_identity='wordpress')

    def test_create_stack(self):
        self._test_engine_api('create_stack', 'call', stack_name='wordpress',
                              template={u'Foo': u'bar'},
                              params={u'InstanceType': u'm1.xlarge'},
                              files={u'a_file': u'the contents'},
                              args={'timeout_mins': u'30'})

    def test_update_stack(self):
        self._test_engine_api('update_stack', 'call',
                              stack_identity=self.identity,
                              template={u'Foo': u'bar'},
                              params={u'InstanceType': u'm1.xlarge'},
                              files={},
                              args={})

    def test_validate_template(self):
        self._test_engine_api('validate_template', 'call',
                              template={u'Foo': u'bar'})

    def test_get_template(self):
        self._test_engine_api('get_template', 'call',
                              stack_identity=self.identity)

    def test_delete_stack_cast(self):
        self._test_engine_api('delete_stack', 'cast',
                              stack_identity=self.identity)

    def test_delete_stack_call(self):
        self._test_engine_api('delete_stack', 'call',
                              stack_identity=self.identity)

    def test_list_events(self):
        self._test_engine_api('list_events', 'call',
                              stack_identity=self.identity)

    def test_describe_stack_resource(self):
        self._test_engine_api('describe_stack_resource', 'call',
                              stack_identity=self.identity,
                              resource_name='LogicalResourceId')

    def test_find_physical_resource(self):
        self._test_engine_api('find_physical_resource', 'call',
                              physical_resource_id=u'404d-a85b-5315293e67de')

    def test_describe_stack_resources(self):
        self._test_engine_api('describe_stack_resources', 'call',
                              stack_identity=self.identity,
                              resource_name=u'WikiDatabase')

    def test_list_stack_resources(self):
        self._test_engine_api('list_stack_resources', 'call',
                              stack_identity=self.identity)

    def test_metadata_update(self):
        self._test_engine_api('metadata_update', 'call',
                              stack_identity=self.identity,
                              resource_name='LogicalResourceId',
                              metadata={u'wordpress': []})

    def test_create_watch_data(self):
        self._test_engine_api('create_watch_data', 'call',
                              watch_name='watch1',
                              stats_data={})

    def test_show_watch(self):
        self._test_engine_api('show_watch', 'call',
                              watch_name='watch1')

    def test_show_watch_metric(self):
        self._test_engine_api('show_watch_metric', 'call',
                              metric_namespace=None, metric_name=None)

    def test_set_watch_state(self):
        self._test_engine_api('set_watch_state', 'call',
                              watch_name='watch1', state="xyz")
