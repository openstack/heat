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

from heat.tests import common

from heat.scaling import rolling_update


class TestNeedsUpdate(common.HeatTestCase):
    scenarios = [
        ('4_4_0', dict(targ=4, curr=4, updated=0, result=True)),
        ('4_4_1', dict(targ=4, curr=4, updated=1, result=True)),
        ('4_4_3', dict(targ=4, curr=4, updated=3, result=True)),
        ('4_4_4', dict(targ=4, curr=4, updated=4, result=False)),
        ('4_4_4', dict(targ=4, curr=4, updated=5, result=False)),
        ('4_5_0', dict(targ=4, curr=5, updated=0, result=True)),
        ('4_5_1', dict(targ=4, curr=5, updated=1, result=True)),
        ('4_5_3', dict(targ=4, curr=5, updated=3, result=True)),
        ('4_5_4', dict(targ=4, curr=5, updated=4, result=True)),
        ('4_5_4', dict(targ=4, curr=5, updated=5, result=True)),
        ('4_3_0', dict(targ=4, curr=3, updated=0, result=True)),
        ('4_3_1', dict(targ=4, curr=3, updated=1, result=True)),
        ('4_3_2', dict(targ=4, curr=3, updated=2, result=True)),
        ('4_3_3', dict(targ=4, curr=3, updated=3, result=True)),
        ('4_3_4', dict(targ=4, curr=3, updated=4, result=True)),
    ]

    def test_needs_update(self):
        needs_update = rolling_update.needs_update(self.targ, self.curr,
                                                   self.updated)
        self.assertEqual(self.result, needs_update)


class TestNextBatch(common.HeatTestCase):

    scenarios = [
        ('4_4_0_1_0', dict(targ=4, curr=4, updated=0, bat_size=1, min_srv=0,
                           batch=(4, 1))),
        ('4_4_3_1_0', dict(targ=4, curr=4, updated=3, bat_size=1, min_srv=0,
                           batch=(4, 1))),
        ('4_4_0_1_4', dict(targ=4, curr=4, updated=0, bat_size=1, min_srv=4,
                           batch=(5, 1))),
        ('4_5_3_1_4', dict(targ=4, curr=5, updated=3, bat_size=1, min_srv=4,
                           batch=(5, 1))),
        ('4_5_4_1_4', dict(targ=4, curr=5, updated=4, bat_size=1, min_srv=4,
                           batch=(4, 0))),
        ('4_4_0_1_5', dict(targ=4, curr=4, updated=0, bat_size=1, min_srv=5,
                           batch=(5, 1))),
        ('4_5_3_1_5', dict(targ=4, curr=5, updated=3, bat_size=1, min_srv=5,
                           batch=(5, 1))),
        ('4_5_0_1_4', dict(targ=4, curr=5, updated=0, bat_size=1, min_srv=4,
                           batch=(5, 1))),
        ('4_5_1_1_4', dict(targ=4, curr=5, updated=1, bat_size=1, min_srv=4,
                           batch=(5, 1))),
        ('4_5_4_1_5', dict(targ=4, curr=5, updated=4, bat_size=1, min_srv=5,
                           batch=(4, 0))),
        ('4_4_0_2_0', dict(targ=4, curr=4, updated=0, bat_size=2, min_srv=0,
                           batch=(4, 2))),
        ('4_4_2_2_0', dict(targ=4, curr=4, updated=2, bat_size=2, min_srv=0,
                           batch=(4, 2))),
        ('4_4_0_2_4', dict(targ=4, curr=4, updated=0, bat_size=2, min_srv=4,
                           batch=(6, 2))),
        ('4_6_2_2_4', dict(targ=4, curr=4, updated=0, bat_size=2, min_srv=4,
                           batch=(6, 2))),
        ('4_6_4_2_4', dict(targ=4, curr=6, updated=4, bat_size=2, min_srv=4,
                           batch=(4, 0))),
        ('5_5_0_2_0', dict(targ=5, curr=5, updated=0, bat_size=2, min_srv=0,
                           batch=(5, 2))),
        ('5_5_4_2_0', dict(targ=5, curr=5, updated=4, bat_size=2, min_srv=0,
                           batch=(5, 1))),
        ('5_5_0_2_4', dict(targ=5, curr=5, updated=0, bat_size=2, min_srv=4,
                           batch=(6, 2))),
        ('5_6_2_2_4', dict(targ=5, curr=6, updated=2, bat_size=2, min_srv=4,
                           batch=(6, 2))),
        ('5_6_4_2_4', dict(targ=5, curr=6, updated=4, bat_size=2, min_srv=4,
                           batch=(5, 1))),
        ('3_3_0_2_0', dict(targ=3, curr=3, updated=0, bat_size=2, min_srv=0,
                           batch=(3, 2))),
        ('3_3_2_2_0', dict(targ=3, curr=3, updated=2, bat_size=2, min_srv=0,
                           batch=(3, 1))),
        ('3_3_0_2_4', dict(targ=3, curr=3, updated=0, bat_size=2, min_srv=4,
                           batch=(5, 2))),
        ('3_5_2_2_4', dict(targ=3, curr=5, updated=2, bat_size=2, min_srv=4,
                           batch=(4, 1))),
        ('3_5_3_2_4', dict(targ=3, curr=5, updated=3, bat_size=2, min_srv=4,
                           batch=(3, 0))),
        ('4_4_0_4_0', dict(targ=4, curr=4, updated=0, bat_size=4, min_srv=0,
                           batch=(4, 4))),
        ('4_4_0_5_0', dict(targ=4, curr=4, updated=0, bat_size=5, min_srv=0,
                           batch=(4, 4))),
        ('4_4_0_4_1', dict(targ=4, curr=4, updated=0, bat_size=4, min_srv=1,
                           batch=(5, 4))),
        ('4_4_4_4_1', dict(targ=4, curr=4, updated=4, bat_size=4, min_srv=1,
                           batch=(4, 0))),
        ('4_4_0_6_1', dict(targ=4, curr=4, updated=0, bat_size=6, min_srv=1,
                           batch=(5, 4))),
        ('4_4_4_6_1', dict(targ=4, curr=4, updated=4, bat_size=6, min_srv=1,
                           batch=(4, 0))),
        ('4_4_0_4_2', dict(targ=4, curr=4, updated=0, bat_size=4, min_srv=2,
                           batch=(6, 4))),
        ('4_4_4_4_2', dict(targ=4, curr=4, updated=4, bat_size=4, min_srv=2,
                           batch=(4, 0))),
        ('4_4_0_4_4', dict(targ=4, curr=4, updated=0, bat_size=4, min_srv=4,
                           batch=(8, 4))),
        ('4_4_4_4_4', dict(targ=4, curr=4, updated=4, bat_size=4, min_srv=4,
                           batch=(4, 0))),
        ('4_4_0_5_6', dict(targ=4, curr=4, updated=0, bat_size=5, min_srv=6,
                           batch=(8, 4))),
        ('4_4_4_5_6', dict(targ=4, curr=4, updated=4, bat_size=5, min_srv=6,
                           batch=(4, 0))),
    ]

    def test_next_batch(self):
        batch = rolling_update.next_batch(self.targ, self.curr,
                                          self.updated,
                                          self.bat_size,
                                          self.min_srv)
        self.assertEqual(self.batch, batch)
