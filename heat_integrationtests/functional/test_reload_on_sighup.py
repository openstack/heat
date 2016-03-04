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

import time

import eventlet

from oslo_concurrency import processutils
from six.moves import configparser

from heat_integrationtests.functional import functional_base


class ReloadOnSighupTest(functional_base.FunctionalTestsBase):

    def setUp(self):
        self.config_file = "/etc/heat/heat.conf"
        super(ReloadOnSighupTest, self).setUp()

    def _set_config_value(self, service, key, value):
        config = configparser.ConfigParser()

        # NOTE(prazumovsky): If there are several workers, there can be
        # situation, when one thread opens self.config_file for writing
        # (so config_file erases with opening), in that moment other thread
        # intercepts to this file and try to set config option value, i.e.
        # write to file, which is already erased by first thread, so,
        # NoSectionError raised. So, should wait until first thread writes to
        # config_file.
        retries_count = self.conf.sighup_config_edit_retries
        while True:
            config.read(self.config_file)
            try:
                config.set(service, key, value)
            except configparser.NoSectionError:
                if retries_count <= 0:
                    raise
                retries_count -= 1
                eventlet.sleep(1)
            else:
                break

        with open(self.config_file, 'wb') as f:
            config.write(f)

    def _get_config_value(self, service, key):
        config = configparser.ConfigParser()
        config.read(self.config_file)
        val = config.get(service, key)
        return val

    def _get_heat_api_pids(self, service):
        # get the pids of all heat-api processes
        if service == "heat_api":
            process = "heat-api|grep -Ev 'grep|cloudwatch|cfn'"
        else:
            process = "%s|grep -Ev 'grep'" % service.replace('_', '-')
        cmd = "ps -ef|grep %s|awk '{print $2}'" % process
        out, err = processutils.execute(cmd, shell=True)
        self.assertIsNotNone(out, "heat-api service not running. %s" % err)
        pids = filter(None, out.split('\n'))

        # get the parent pids of all heat-api processes
        cmd = "ps -ef|grep %s|awk '{print $3}'" % process
        out, _ = processutils.execute(cmd, shell=True)
        parent_pids = filter(None, out.split('\n'))

        heat_api_parent = list(set(pids) & set(parent_pids))[0]
        heat_api_children = list(set(pids) - set(parent_pids))

        return heat_api_parent, heat_api_children

    def _change_config(self, service, old_workers, new_workers):
        pre_reload_parent, pre_reload_children = self._get_heat_api_pids(
            service)
        self.assertEqual(old_workers, len(pre_reload_children))

        # change the config values
        self._set_config_value(service, 'workers', new_workers)
        cmd = "kill -HUP %s" % pre_reload_parent
        processutils.execute(cmd, shell=True)

        # wait till heat-api reloads
        start_time = time.time()
        while time.time() - start_time < self.conf.sighup_timeout:
            post_reload_parent, post_reload_children = self._get_heat_api_pids(
                service)
            intersect = set(post_reload_children) & set(pre_reload_children)
            if (new_workers == len(post_reload_children)
                and pre_reload_parent == post_reload_parent
                    and intersect == set()):
                break
            eventlet.sleep(1)
        self.assertEqual(pre_reload_parent, post_reload_parent)
        self.assertEqual(new_workers, len(post_reload_children))
        # test if all child processes are newly created
        self.assertEqual(set(post_reload_children) & set(pre_reload_children),
                         set())

    def _reload(self, service):
        old_workers = int(self._get_config_value(service, 'workers'))
        new_workers = old_workers + 1
        self.addCleanup(self._set_config_value, service, 'workers',
                        old_workers)

        self._change_config(service, old_workers, new_workers)
        # revert all the changes made
        self._change_config(service, new_workers, old_workers)

    def test_api_reload_on_sighup(self):
        self._reload('heat_api')

    def test_api_cfn_reload_on_sighup(self):
        self._reload('heat_api_cfn')

    def test_api_cloudwatch_on_sighup(self):
        self._reload('heat_api_cloudwatch')
