import nose
import unittest
from nose.plugins.attrib import attr

from heat.engine.parser import _resolve as resolve


def join(raw):
    def handle_join(args):
        delim, strs = args
        return delim.join(strs)

    return resolve(lambda k, v: k == 'Fn::Join', handle_join, raw)


@attr(tag=['unit', 'parser'])
@attr(speed='fast')
class ParserTest(unittest.TestCase):

    def test_list(self):
        raw = ['foo', 'bar', 'baz']
        parsed = join(raw)
        for i in xrange(len(raw)):
            self.assertEqual(parsed[i], raw[i])
        self.assertTrue(parsed is not raw)

    def test_dict(self):
        raw = {'foo': 'bar', 'blarg': 'wibble'}
        parsed = join(raw)
        for k in raw:
            self.assertEqual(parsed[k], raw[k])
        self.assertTrue(parsed is not raw)

    def test_dict_list(self):
        raw = {'foo': ['bar', 'baz'], 'blarg': 'wibble'}
        parsed = join(raw)
        self.assertEqual(parsed['blarg'], raw['blarg'])
        for i in xrange(len(raw['foo'])):
            self.assertEqual(parsed['foo'][i], raw['foo'][i])
        self.assertTrue(parsed is not raw)
        self.assertTrue(parsed['foo'] is not raw['foo'])

    def test_list_dict(self):
        raw = [{'foo': 'bar', 'blarg': 'wibble'}, 'baz', 'quux']
        parsed = join(raw)
        for i in xrange(1, len(raw)):
            self.assertEqual(parsed[i], raw[i])
        for k in raw[0]:
            self.assertEqual(parsed[0][k], raw[0][k])
        self.assertTrue(parsed is not raw)
        self.assertTrue(parsed[0] is not raw[0])

    def test_join(self):
        raw = {'Fn::Join': [' ', ['foo', 'bar', 'baz']]}
        self.assertEqual(join(raw), 'foo bar baz')

    def test_join_list(self):
        raw = [{'Fn::Join': [' ', ['foo', 'bar', 'baz']]}, 'blarg', 'wibble']
        parsed = join(raw)
        self.assertEqual(parsed[0], 'foo bar baz')
        for i in xrange(1, len(raw)):
            self.assertEqual(parsed[i], raw[i])
        self.assertTrue(parsed is not raw)

    def test_join_dict_val(self):
        raw = {'quux': {'Fn::Join': [' ', ['foo', 'bar', 'baz']]},
               'blarg': 'wibble'}
        parsed = join(raw)
        self.assertEqual(parsed['quux'], 'foo bar baz')
        self.assertEqual(parsed['blarg'], raw['blarg'])
        self.assertTrue(parsed is not raw)

    def test_join_recursive(self):
        raw = {'Fn::Join': ['\n', [{'Fn::Join': [' ', ['foo', 'bar']]},
                                  'baz']]}
        self.assertEqual(join(raw), 'foo bar\nbaz')


# allows testing of the test directly, shown below
if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
