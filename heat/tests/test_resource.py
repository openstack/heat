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


import nose
import unittest
from nose.plugins.attrib import attr
import mox

import json
from heat.common import context
from heat.engine import parser
from heat.engine import resources


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class ResourceTest(unittest.TestCase):
    def setUp(self):
        self.stack = parser.Stack(None, 'test_stack', parser.Template({}))

    def test_state_defaults(self):
        tmpl = {'Type': 'Foo'}
        res = resources.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(res.state, None)
        self.assertEqual(res.state_description, '')

    def test_state(self):
        tmpl = {'Type': 'Foo'}
        res = resources.GenericResource('test_resource', tmpl, self.stack)
        res.state_set('bar')
        self.assertEqual(res.state, 'bar')

    def test_state_description(self):
        tmpl = {'Type': 'Foo'}
        res = resources.GenericResource('test_resource', tmpl, self.stack)
        res.state_set('blarg', 'wibble')
        self.assertEqual(res.state_description, 'wibble')

    def test_parsed_template(self):
        tmpl = {
            'Type': 'Foo',
            'foo': {'Fn::Join': [' ', ['bar', 'baz', 'quux']]}
        }
        res = resources.GenericResource('test_resource', tmpl, self.stack)

        parsed_tmpl = res.parsed_template()
        self.assertEqual(parsed_tmpl['Type'], 'Foo')
        self.assertEqual(parsed_tmpl['foo'], 'bar baz quux')

        self.assertEqual(res.parsed_template('foo'), 'bar baz quux')
        self.assertEqual(res.parsed_template('foo', 'bar'), 'bar baz quux')

    def test_parsed_template_default(self):
        tmpl = {'Type': 'Foo'}
        res = resources.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(res.parsed_template('foo'), {})
        self.assertEqual(res.parsed_template('foo', 'bar'), 'bar')

    def test_metadata_default(self):
        tmpl = {'Type': 'Foo'}
        res = resources.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(res.metadata, {})


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class MetadataTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        tmpl = {
            'Type': 'Foo',
            'Metadata': {'Test': 'Initial metadata'}
        }
        ctx = context.get_admin_context()
        self.m.StubOutWithMock(ctx, 'username')
        ctx.username = 'metadata_test_user'
        self.stack = parser.Stack(ctx, 'test_stack', parser.Template({}))
        self.stack.store()
        self.res = resources.GenericResource('metadata_resource',
                                             tmpl, self.stack)
        self.res.create()

    def tearDown(self):
        self.stack.delete()
        self.m.UnsetStubs()

    def test_read_initial(self):
        self.assertEqual(self.res.metadata, {'Test': 'Initial metadata'})

    def test_write(self):
        test_data = {'Test': 'Newly-written data'}
        self.res.metadata = test_data
        self.assertEqual(self.res.metadata, test_data)

# allows testing of the test directly, shown below
if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
