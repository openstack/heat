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

import mock

from heat.db.sqlalchemy import filters as db_filters
from heat.tests import common


class ExactFilterTest(common.HeatTestCase):
    def setUp(self):
        super(ExactFilterTest, self).setUp()
        self.query = mock.Mock()
        self.model = mock.Mock()

    def test_returns_same_query_for_empty_filters(self):
        filters = {}
        db_filters.exact_filter(self.query, self.model, filters)
        self.assertEqual(0, self.query.call_count)

    def test_add_exact_match_clause_for_single_values(self):
        filters = {'cat': 'foo'}
        db_filters.exact_filter(self.query, self.model, filters)

        self.query.filter_by.assert_called_once_with(cat='foo')

    def test_adds_an_in_clause_for_multiple_values(self):
        self.model.cat.in_.return_value = 'fake in clause'
        filters = {'cat': ['foo', 'quux']}
        db_filters.exact_filter(self.query, self.model, filters)

        self.query.filter.assert_called_once_with('fake in clause')
        self.model.cat.in_.assert_called_once_with(['foo', 'quux'])
