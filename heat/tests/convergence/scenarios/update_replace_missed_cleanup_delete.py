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


def check_c_count(expected_count):
    test.assertEqual(expected_count,
                     len(reality.resources_by_logical_name('C')))

example_template = Template({
    'A': RsrcDef({'a': 'initial'}, []),
    'B': RsrcDef({}, []),
    'C': RsrcDef({'!a': GetAtt('A', 'a')}, ['B']),
    'D': RsrcDef({'c': GetRes('C')}, []),
    'E': RsrcDef({'ca': GetAtt('C', '!a')}, []),
})
engine.create_stack('foo', example_template)
engine.noop(5)
engine.call(verify, example_template)

example_template_shrunk = Template({
    'A': RsrcDef({'a': 'updated'}, []),
    'B': RsrcDef({}, []),
    'C': RsrcDef({'!a': GetAtt('A', 'a')}, ['B']),
    'D': RsrcDef({'c': GetRes('C')}, []),
    'E': RsrcDef({'ca': GetAtt('C', '!a')}, []),
})
engine.update_stack('foo', example_template_shrunk)
engine.noop(7)

engine.delete_stack('foo')
engine.call(check_c_count, 2)
engine.noop(11)
engine.call(verify, Template({}))
