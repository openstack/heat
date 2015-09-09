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


def check_resource_counts(count_map):
    for name, count in count_map.items():
        test.assertEqual(count,
                         len(list(reality.resources_by_logical_name(name))))


example_template = Template({
    'A': RsrcDef({'!a': 'initial'}, []),
    'B': RsrcDef({'!b': 'first'}, ['A']),
})
engine.create_stack('foo', example_template)
engine.noop(4)
engine.call(verify, example_template)

example_template_inverted = Template({
    'A': RsrcDef({'!a': 'updated'}, ['B']),
    'B': RsrcDef({'!b': 'second'}, []),
})
engine.update_stack('foo', example_template_inverted)
engine.noop(4)
engine.call(check_resource_counts, {'A': 2, 'B': 1})
engine.noop(2)
engine.call(verify, example_template_inverted)
engine.call(check_resource_counts, {'A': 1, 'B': 1})

engine.delete_stack('foo')
engine.noop(3)
engine.call(verify, Template({}))
