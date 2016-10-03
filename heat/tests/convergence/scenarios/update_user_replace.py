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


c_uuid = None

def store_c_uuid():
    global c_uuid
    c_uuid = next(iter(reality.resources_by_logical_name('C'))).uuid

def check_c_replaced():
    test.assertNotEqual(c_uuid,
                        next(iter(reality.resources_by_logical_name('newC'))).uuid)
    test.assertIsNotNone(c_uuid)


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
engine.call(store_c_uuid)

example_template_updated = Template({
    'A': RsrcDef({'a': 'updated'}, []),
    'B': RsrcDef({}, []),
    'newC': RsrcDef({'!a': GetAtt('A', 'a')}, ['B']),
    'D': RsrcDef({'c': GetRes('newC')}, []),
    'E': RsrcDef({'ca': GetAtt('newC', '!a')}, []),
})
engine.update_stack('foo', example_template_updated)
engine.noop(11)
engine.call(verify, example_template_updated)

example_template_long = Template({
    'A': RsrcDef({'a': 'updated'}, []),
    'B': RsrcDef({}, []),
    'newC': RsrcDef({'!a': GetAtt('A', 'a')}, ['B']),
    'D': RsrcDef({'c': GetRes('newC')}, []),
    'E': RsrcDef({'ca': GetAtt('newC', '!a')}, []),
    'F': RsrcDef({}, ['D', 'E']),
})
engine.update_stack('foo', example_template_long)
engine.noop(12)
engine.call(verify, example_template_long)
engine.call(check_c_replaced)

engine.delete_stack('foo')
engine.noop(6)
engine.call(verify, Template({}))
