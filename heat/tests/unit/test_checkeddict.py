import sys
import os

import nose
import unittest
import mox
import json

from nose.plugins.attrib import attr
from nose import with_setup

from heat.engine import checkeddict


@attr(tag=['unit', 'checkeddict'])
@attr(speed='fast')
class CheckedDictTest(unittest.TestCase):

    def test_paramerters(self):
        parms = '''
{
  "Parameters" : {
    "TODOList" : {
      "Description" : "stuff",
      "Type" : "CommaDelimitedList"
    },
    "SomeNumber" : {
      "Type" : "Number",
      "Default" : "56",
      "MaxValue": "6778",
      "MinValue": "15.78"
    },
    "DBUsername": {
      "Default": "admin",
      "NoEcho": "true",
      "Description" : "The WordPress database admin account username",
      "Type": "String",
      "MinLength": "1",
      "MaxLength": "16",
      "AllowedPattern" : "[a-zA-Z][a-zA-Z0-9]*",
      "ConstraintDescription" : "begin with a letter & \
          contain only alphanumeric characters."
    },
    "LinuxDistribution": {
      "Default": "F16",
      "Description" : "Distribution of choice",
      "Type": "String",
      "AllowedValues" : [ "F16", "F17", "U10", "RHEL-6.1", "RHEL-6.3" ]
    }
 }
}
'''
        ps = json.loads(parms)
        cd = checkeddict.CheckedDict('test_paramerters')
        for p in ps['Parameters']:
            cd.addschema(p, ps['Parameters'][p])

        # AllowedValues
        self.assertRaises(ValueError, cd.__setitem__, 'LinuxDistribution',
                          'f16')
        # MaxLength
        self.assertRaises(ValueError, cd.__setitem__, 'DBUsername',
                          'Farstarststrststrstrstrst144')
        # MinLength
        self.assertRaises(ValueError, cd.__setitem__, 'DBUsername', '')
        # AllowedPattern
        self.assertRaises(ValueError, cd.__setitem__, 'DBUsername', '4me')

        cd['DBUsername'] = 'wtf'
        self.assertTrue(cd['DBUsername'] == 'wtf')
        cd['LinuxDistribution'] = 'U10'
        self.assertTrue(cd['LinuxDistribution'] == 'U10')

        # int
        cd['SomeNumber'] = '98'
        self.assertTrue(cd['SomeNumber'] == '98')

        # float
        cd['SomeNumber'] = '54.345'
        self.assertTrue(cd['SomeNumber'] == '54.345')

        # not a num
        self.assertRaises(ValueError, cd.__setitem__, 'SomeNumber', 'S8')
        # range errors
        self.assertRaises(ValueError, cd.__setitem__, 'SomeNumber', '8')
        self.assertRaises(ValueError, cd.__setitem__, 'SomeNumber', '9048.56')
        # lists
        cd['TODOList'] = "'one', 'two', 'three'"
