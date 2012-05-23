# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import collections
import re


class CheckedDict(collections.MutableMapping):

    def __init__(self):
        self.data = {}

    def addschema(self, key, schema):
        self.data[key] = schema

    def get_attr(self, key, attr):
        return self.data[key].get(attr, '')

    def __setitem__(self, key, value):
        '''Since this function gets called whenever we modify the
        dictionary (object), we can (and do) validate those keys that we
        know how to validate.
        '''
        def str_to_num(s):
            try:
                return int(s)
            except ValueError:
                return float(s)

        num_converter = {'Integer': int,
                         'Number': str_to_num,
                         'Float': float}

        if not key in self.data:
            raise KeyError('key %s not found' % key)

        if 'Type' in self.data[key]:
            t = self.data[key]['Type']
            if self.data[key]['Type'] == 'String':
                if not isinstance(value, (basestring, unicode)):
                    raise ValueError('%s Value must be a string' % \
                                     (key))
                if 'MaxLength' in self.data[key]:
                    if len(value) > int(self.data[key]['MaxLength']):
                        raise ValueError('%s is too long; MaxLength %s' % \
                                     (key, self.data[key]['MaxLength']))
                if 'MinLength' in self.data[key]:
                    if len(value) < int(self.data[key]['MinLength']):
                        raise ValueError('%s is too short; MinLength  %s' % \
                                     (key, self.data[key]['MinLength']))
                if 'AllowedPattern' in self.data[key]:
                    rc = re.match('^%s$' % self.data[key]['AllowedPattern'],
                                  value)
                    if rc == None:
                        raise ValueError('Pattern does not match %s' % \
                                     (key))

            elif self.data[key]['Type'] in ['Integer', 'Number', 'Float']:
                # just try convert and see if it will throw a ValueError
                num = num_converter[t](value)
                minn = num
                maxn = num
                if 'MaxValue' in self.data[key]:
                    maxn = num_converter[t](self.data[key]['MaxValue'])
                if 'MinValue' in self.data[key]:
                    minn = num_converter[t](self.data[key]['MinValue'])
                if num > maxn or num < minn:
                    raise ValueError('%s is out of range' % key)

            elif self.data[key]['Type'] == 'List':
                if not isinstance(value, list):
                    raise ValueError('%s Value must be a list' % (key))

            elif self.data[key]['Type'] == 'CommaDelimitedList':
                sp = value.split(',')
                if not isinstance(sp, list):
                    raise ValueError('%s Value must be a list' % (key))

        if 'AllowedValues' in self.data[key]:
            if not value in self.data[key]['AllowedValues']:
                raise ValueError('Value must be one of %s' % \
                                 str(self.data[key]['AllowedValues']))

        self.data[key]['Value'] = value

    def __getitem__(self, key):
        if not key in self.data:
            raise KeyError('key %s not found' % key)

        if 'Value' in self.data[key]:
            return self.data[key]['Value']
        elif 'Default' in self.data[key]:
            return self.data[key]['Default']
        elif 'Required' in self.data[key]:
            if not self.data[key]['Required']:
                return None
            else:
                raise ValueError('%s must be provided' % key)
        else:
            raise ValueError('%s must be provided' % key)

    def __len__(self):
        return len(self.data)

    def __contains__(self, key):
        return key in self.data

    def __iter__(self):
        return iter(self.data)

    def __delitem__(self, k):
        del self.data[k]


class Properties(CheckedDict):
    def __init__(self, schema):
        CheckedDict.__init__(self)
        self.data = schema

        # set some defaults
        for s in self.data:
            if not 'Implemented' in self.data[s]:
                self.data[s]['Implemented'] = True
            if not 'Required' in self.data[s]:
                self.data[s]['Required'] = False

    def validate(self):
        for key in self.data:
            # are there missing required Properties
            if 'Required' in self.data[key]:
                if self.data[key]['Required'] \
                    and not 'Value' in self.data[key]:
                    return {'Error': \
                        '%s Property must be provided' % key}

            # are there unimplemented Properties
            if not self.data[key]['Implemented'] and 'Value' in self.data[key]:
                return {'Error': \
                    '%s Property not implemented yet' % key}
        return None
