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

from heat.engine.clients import progress
from heat.tests import common


class ServerUpdateProgressObjectTest(common.HeatTestCase):

    def setUp(self):
        super(ServerUpdateProgressObjectTest, self).setUp()
        self.server_id = '1234'
        self.handler = 'test'

    def _assert_common(self, prg):
        self.assertEqual(self.server_id, prg.server_id)
        self.assertEqual(self.handler, prg.handler)
        self.assertEqual('check_%s' % self.handler, prg.checker)
        self.assertFalse(prg.called)
        self.assertFalse(prg.complete)

    def test_extra_all_defaults(self):
        prg = progress.ServerUpdateProgress(self.server_id, self.handler)
        self._assert_common(prg)
        self.assertEqual((self.server_id,), prg.handler_args)
        self.assertEqual((self.server_id,), prg.checker_args)
        self.assertEqual({}, prg.handler_kwargs)
        self.assertEqual({}, prg.checker_kwargs)

    def test_handler_extra_kwargs_missing(self):
        handler_extra = {'args': ()}
        prg = progress.ServerUpdateProgress(self.server_id, self.handler,
                                            handler_extra=handler_extra)
        self._assert_common(prg)
        self.assertEqual((self.server_id,), prg.handler_args)
        self.assertEqual((self.server_id,), prg.checker_args)
        self.assertEqual({}, prg.handler_kwargs)
        self.assertEqual({}, prg.checker_kwargs)
