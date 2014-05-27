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

# See http://code.google.com/p/python-nose/issues/detail?id=373
# The code below enables nosetests to work with i18n _() blocks
from heat.openstack.common import gettextutils


def fake_translate_msgid(msgid, domain, desired_locale=None):
    return msgid

gettextutils.enable_lazy()
gettextutils.install('heat', lazy=True)

#To ensure messages don't really get translated while running tests.
#As there are lots of places where matching is expected when comparing
#exception message(translated) with raw message.
gettextutils._translate_msgid = fake_translate_msgid
