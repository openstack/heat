import nose
import unittest
from nose.plugins.attrib import attr

import heat.engine.manager as manager


@attr(tag=['unit', 'manager'])
@attr(speed='fast')
class managerTest(unittest.TestCase):
    def test_params_extract(self):
        p = {'Parameters.member.Foo.ParameterKey': 'foo',
             'Parameters.member.Foo.ParameterValue': 'bar',
             'Parameters.member.Blarg.ParameterKey': 'blarg',
             'Parameters.member.Blarg.ParameterValue': 'wibble'}
        params = manager._extract_user_params(p)
        self.assertEqual(len(params), 2)
        self.assertTrue('foo' in params)
        self.assertEqual(params['foo'], 'bar')
        self.assertTrue('blarg' in params)
        self.assertEqual(params['blarg'], 'wibble')

    def test_params_extract_dots(self):
        p = {'Parameters.member.Foo.Bar.ParameterKey': 'foo',
             'Parameters.member.Foo.Bar.ParameterValue': 'bar',
             'Parameters.member.Foo.Baz.ParameterKey': 'blarg',
             'Parameters.member.Foo.Baz.ParameterValue': 'wibble'}
        params = manager._extract_user_params(p)
        self.assertEqual(len(params), 2)
        self.assertTrue('foo' in params)
        self.assertEqual(params['foo'], 'bar')
        self.assertTrue('blarg' in params)
        self.assertEqual(params['blarg'], 'wibble')

    def test_params_extract_garbage(self):
        p = {'Parameters.member.Foo.Bar.ParameterKey': 'foo',
             'Parameters.member.Foo.Bar.ParameterValue': 'bar',
             'Foo.Baz.ParameterKey': 'blarg',
             'Foo.Baz.ParameterValue': 'wibble'}
        params = manager._extract_user_params(p)
        self.assertEqual(len(params), 1)
        self.assertTrue('foo' in params)
        self.assertEqual(params['foo'], 'bar')

    def test_params_extract_garbage_prefix(self):
        p = {'prefixParameters.member.Foo.Bar.ParameterKey': 'foo',
             'Parameters.member.Foo.Bar.ParameterValue': 'bar'}
        params = manager._extract_user_params(p)
        self.assertFalse(params)

    def test_params_extract_garbage_suffix(self):
        p = {'Parameters.member.Foo.Bar.ParameterKeysuffix': 'foo',
             'Parameters.member.Foo.Bar.ParameterValue': 'bar'}
        params = manager._extract_user_params(p)
        self.assertFalse(params)
