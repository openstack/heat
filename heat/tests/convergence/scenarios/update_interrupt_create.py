def check_resource_count(expected_count):
    test.assertEqual(expected_count, len(reality.all_resources()))

example_template = Template({
    'A': RsrcDef({}, []),
    'B': RsrcDef({'a': '4alpha'}, ['A']),
    'C': RsrcDef({'a': 'foo'}, ['B']),
    'D': RsrcDef({'a': 'bar'}, ['C']),
})
engine.create_stack('foo', example_template)
engine.noop(1)

example_template2 = Template({
    'A': RsrcDef({}, []),
    'B': RsrcDef({'a': '4alpha'}, ['A']),
    'C': RsrcDef({'a': 'blarg'}, ['B']),
    'D': RsrcDef({'a': 'wibble'}, ['C']),
})
engine.update_stack('foo', example_template2)
engine.call(check_resource_count, 2)
engine.noop(11)
engine.call(verify, example_template2)
