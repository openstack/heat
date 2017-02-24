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


from heat.engine import node_data

from heat.tests import common


def make_test_data():
    return {
        'id': 42,
        'name': 'foo',
        'reference_id': 'foo-000000',
        'attrs': {
            'foo': 'bar',
            ('foo', 'bar', 'baz'): 'quux',
            ('blarg', 'wibble'): 'foo',
        },
        'action': 'CREATE',
        'status': 'COMPLETE',
        'uuid': '000000-0000-0000-0000000',
    }


def make_test_node():
    return node_data.NodeData.from_dict(make_test_data())


class NodeDataTest(common.HeatTestCase):
    def test_round_trip(self):
        in_dict = make_test_data()
        self.assertEqual(in_dict,
                         node_data.NodeData.from_dict(in_dict).as_dict())

    def test_resource_key(self):
        nd = make_test_node()
        self.assertEqual(42, nd.primary_key)

    def test_resource_name(self):
        nd = make_test_node()
        self.assertEqual('foo', nd.name)

    def test_action(self):
        nd = make_test_node()
        self.assertEqual('CREATE', nd.action)

    def test_status(self):
        nd = make_test_node()
        self.assertEqual('COMPLETE', nd.status)

    def test_refid(self):
        nd = make_test_node()
        self.assertEqual('foo-000000', nd.reference_id())

    def test_all_attrs(self):
        nd = make_test_node()
        self.assertEqual({'foo': 'bar'}, nd.attributes())

    def test_attr(self):
        nd = make_test_node()
        self.assertEqual('bar', nd.attribute('foo'))

    def test_path_attr(self):
        nd = make_test_node()
        self.assertEqual('quux', nd.attribute(('foo', 'bar', 'baz')))

    def test_attr_names(self):
        nd = make_test_node()
        self.assertEqual({'foo', 'blarg'}, set(nd.attribute_names()))
