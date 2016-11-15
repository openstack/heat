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

import six

from heat.common import exception
from heat.engine import properties_group as pg
from heat.tests import common


class TestSchemaSimpleValidation(common.HeatTestCase):

    scenarios = [
        ('correct schema', dict(
            schema={pg.AND: [['a'], ['b']]},
            message=None,
        )),
        ('invalid type schema', dict(
            schema=[{pg.OR: [['a'], ['b']]}],
            message="Properties group schema incorrectly specified. "
                    "Schema should be a mapping, "
                    "found %s instead." % list,
        )),
        ('invalid type subschema', dict(
            schema={pg.OR: [['a'], ['b'], [{pg.XOR: [['c'], ['d']]}]]},
            message='Properties group schema incorrectly specified. List '
                    'items should be properties list-type names with format '
                    '"[prop, prop_child, prop_sub_child, ...]" or nested '
                    'properties group schemas.',
        )),
        ('several keys schema', dict(
            schema={pg.OR: [['a'], ['b']],
                    pg.XOR: [['v', 'g']]},
            message='Properties group schema incorrectly specified. Schema '
                    'should be one-key dict.',
        )),
        ('several keys subschema', dict(
            schema={pg.OR: [['a'], ['b'], {pg.XOR: [['c']], pg.OR: ['d']}]},
            message='Properties group schema incorrectly specified. '
                    'Schema should be one-key dict.',
        )),
        ('invalid key schema', dict(
            schema={'NOT KEY': [['a'], ['b']]},
            message='Properties group schema incorrectly specified. '
                    'Properties group schema key should be one of the '
                    'operators: AND, OR, XOR.',
        )),
        ('invalid key subschema', dict(
            schema={pg.AND: [['a'], {'NOT KEY': [['b']]}]},
            message='Properties group schema incorrectly specified. '
                    'Properties group schema key should be one of the '
                    'operators: AND, OR, XOR.',
        )),
        ('invalid value type schema', dict(
            schema={pg.OR: 'a'},
            message="Properties group schema incorrectly specified. "
                    "Schemas' values should be lists of properties names "
                    "or nested schemas.",
        )),
        ('invalid value type subschema', dict(
            schema={pg.OR: [{pg.XOR: 'a'}]},
            message="Properties group schema incorrectly specified. "
                    "Schemas' values should be lists of properties names "
                    "or nested schemas.",
        )),
        ('invalid prop name schema', dict(
            schema={pg.OR: ['a', 'b']},
            message='Properties group schema incorrectly specified. List '
                    'items should be properties list-type names with format '
                    '"[prop, prop_child, prop_sub_child, ...]" or nested '
                    'properties group schemas.',
        )),
    ]

    def test_properties_group_schema_validate(self):
        if self.message is not None:
            ex = self.assertRaises(exception.InvalidSchemaError,
                                   pg.PropertiesGroup, self.schema)
            self.assertEqual(self.message, six.text_type(ex))
        else:
            self.assertIsInstance(pg.PropertiesGroup(self.schema),
                                  pg.PropertiesGroup)
