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

import logging
import os
import random
import re
import subprocess
import time

import fixtures
from heatclient import exc as heat_exceptions
from oslo.utils import timeutils
import six
import testscenarios
import testtools

from heat_integrationtests.common import clients
from heat_integrationtests.common import config
from heat_integrationtests.common import exceptions
from heat_integrationtests.common import remote_client

LOG = logging.getLogger(__name__)
_LOG_FORMAT = "%(levelname)8s [%(name)s] %(message)s"


def call_until_true(func, duration, sleep_for):
    """
    Call the given function until it returns True (and return True) or
    until the specified duration (in seconds) elapses (and return
    False).

    :param func: A zero argument callable that returns True on success.
    :param duration: The number of seconds for which to attempt a
        successful call of the function.
    :param sleep_for: The number of seconds to sleep after an unsuccessful
                      invocation of the function.
    """
    now = time.time()
    timeout = now + duration
    while now < timeout:
        if func():
            return True
        LOG.debug("Sleeping for %d seconds", sleep_for)
        time.sleep(sleep_for)
        now = time.time()
    return False


def rand_name(name=''):
    randbits = str(random.randint(1, 0x7fffffff))
    if name:
        return name + '-' + randbits
    else:
        return randbits


class HeatIntegrationTest(testscenarios.WithScenarios,
                          testtools.TestCase):

    def setUp(self):
        super(HeatIntegrationTest, self).setUp()

        self.conf = config.init_conf()

        self.assertIsNotNone(self.conf.auth_url,
                             'No auth_url configured')
        self.assertIsNotNone(self.conf.username,
                             'No username configured')
        self.assertIsNotNone(self.conf.password,
                             'No password configured')

        self.manager = clients.ClientManager(self.conf)
        self.identity_client = self.manager.identity_client
        self.orchestration_client = self.manager.orchestration_client
        self.compute_client = self.manager.compute_client
        self.network_client = self.manager.network_client
        self.volume_client = self.manager.volume_client
        self.object_client = self.manager.object_client
        self.useFixture(fixtures.FakeLogger(format=_LOG_FORMAT))

    def status_timeout(self, things, thing_id, expected_status,
                       error_status='ERROR',
                       not_found_exception=heat_exceptions.NotFound):
        """
        Given a thing and an expected status, do a loop, sleeping
        for a configurable amount of time, checking for the
        expected status to show. At any time, if the returned
        status of the thing is ERROR, fail out.
        """
        self._status_timeout(things, thing_id,
                             expected_status=expected_status,
                             error_status=error_status,
                             not_found_exception=not_found_exception)

    def _status_timeout(self,
                        things,
                        thing_id,
                        expected_status=None,
                        allow_notfound=False,
                        error_status='ERROR',
                        not_found_exception=heat_exceptions.NotFound):

        log_status = expected_status if expected_status else ''
        if allow_notfound:
            log_status += ' or NotFound' if log_status != '' else 'NotFound'

        def check_status():
            # python-novaclient has resources available to its client
            # that all implement a get() method taking an identifier
            # for the singular resource to retrieve.
            try:
                thing = things.get(thing_id)
            except not_found_exception:
                if allow_notfound:
                    return True
                raise
            except Exception as e:
                if allow_notfound and self.not_found_exception(e):
                    return True
                raise

            new_status = thing.status

            # Some components are reporting error status in lower case
            # so case sensitive comparisons can really mess things
            # up.
            if new_status.lower() == error_status.lower():
                message = ("%s failed to get to expected status (%s). "
                           "In %s state.") % (thing, expected_status,
                                              new_status)
                raise exceptions.BuildErrorException(message,
                                                     server_id=thing_id)
            elif new_status == expected_status and expected_status is not None:
                return True  # All good.
            LOG.debug("Waiting for %s to get to %s status. "
                      "Currently in %s status",
                      thing, log_status, new_status)
        if not call_until_true(
                check_status,
                self.conf.build_timeout,
                self.conf.build_interval):
            message = ("Timed out waiting for thing %s "
                       "to become %s") % (thing_id, log_status)
            raise exceptions.TimeoutException(message)

    def get_remote_client(self, server_or_ip, username, private_key=None):
        if isinstance(server_or_ip, six.string_types):
            ip = server_or_ip
        else:
            network_name_for_ssh = self.conf.network_for_ssh
            ip = server_or_ip.networks[network_name_for_ssh][0]
        if private_key is None:
            private_key = self.keypair.private_key
        linux_client = remote_client.RemoteClient(ip, username,
                                                  pkey=private_key,
                                                  conf=self.conf)
        try:
            linux_client.validate_authentication()
        except exceptions.SSHTimeout:
            LOG.exception('ssh connection to %s failed' % ip)
            raise

        return linux_client

    def _log_console_output(self, servers=None):
        if not servers:
            servers = self.compute_client.servers.list()
        for server in servers:
            LOG.debug('Console output for %s', server.id)
            LOG.debug(server.get_console_output())

    def _load_template(self, base_file, file_name):
        filepath = os.path.join(os.path.dirname(os.path.realpath(base_file)),
                                file_name)
        with open(filepath) as f:
            return f.read()

    def create_keypair(self, client=None, name=None):
        if client is None:
            client = self.compute_client
        if name is None:
            name = rand_name('heat-keypair')
        keypair = client.keypairs.create(name)
        self.assertEqual(keypair.name, name)

        def delete_keypair():
            keypair.delete()

        self.addCleanup(delete_keypair)
        return keypair

    @classmethod
    def _stack_rand_name(cls):
        return rand_name(cls.__name__)

    def _get_default_network(self):
        networks = self.network_client.list_networks()
        for net in networks['networks']:
            if net['name'] == self.conf.fixed_network_name:
                return net

    @staticmethod
    def _stack_output(stack, output_key):
        """Return a stack output value for a given key."""
        return next((o['output_value'] for o in stack.outputs
                    if o['output_key'] == output_key), None)

    def _ping_ip_address(self, ip_address, should_succeed=True):
        cmd = ['ping', '-c1', '-w1', ip_address]

        def ping():
            proc = subprocess.Popen(cmd,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            proc.wait()
            return (proc.returncode == 0) == should_succeed

        return call_until_true(
            ping, self.conf.build_timeout, 1)

    def _wait_for_resource_status(self, stack_identifier, resource_name,
                                  status, failure_pattern='^.*_FAILED$',
                                  success_on_not_found=False):
        """Waits for a Resource to reach a given status."""
        fail_regexp = re.compile(failure_pattern)
        build_timeout = self.conf.build_timeout
        build_interval = self.conf.build_interval

        start = timeutils.utcnow()
        while timeutils.delta_seconds(start,
                                      timeutils.utcnow()) < build_timeout:
            try:
                res = self.client.resources.get(
                    stack_identifier, resource_name)
            except heat_exceptions.HTTPNotFound:
                if success_on_not_found:
                    return
                # ignore this, as the resource may not have
                # been created yet
            else:
                if res.resource_status == status:
                    return
                if fail_regexp.search(res.resource_status):
                    raise exceptions.StackResourceBuildErrorException(
                        resource_name=res.resource_name,
                        stack_identifier=stack_identifier,
                        resource_status=res.resource_status,
                        resource_status_reason=res.resource_status_reason)
            time.sleep(build_interval)

        message = ('Resource %s failed to reach %s status within '
                   'the required time (%s s).' %
                   (res.resource_name, status, build_timeout))
        raise exceptions.TimeoutException(message)

    def _wait_for_stack_status(self, stack_identifier, status,
                               failure_pattern='^.*_FAILED$',
                               success_on_not_found=False):
        """
        Waits for a Stack to reach a given status.

        Note this compares the full $action_$status, e.g
        CREATE_COMPLETE, not just COMPLETE which is exposed
        via the status property of Stack in heatclient
        """
        fail_regexp = re.compile(failure_pattern)
        build_timeout = self.conf.build_timeout
        build_interval = self.conf.build_interval

        start = timeutils.utcnow()
        while timeutils.delta_seconds(start,
                                      timeutils.utcnow()) < build_timeout:
            try:
                stack = self.client.stacks.get(stack_identifier)
            except heat_exceptions.HTTPNotFound:
                if success_on_not_found:
                    return
                # ignore this, as the resource may not have
                # been created yet
            else:
                if stack.stack_status == status:
                    return
                if fail_regexp.search(stack.stack_status):
                    raise exceptions.StackBuildErrorException(
                        stack_identifier=stack_identifier,
                        stack_status=stack.stack_status,
                        stack_status_reason=stack.stack_status_reason)
            time.sleep(build_interval)

        message = ('Stack %s failed to reach %s status within '
                   'the required time (%s s).' %
                   (stack.stack_name, status, build_timeout))
        raise exceptions.TimeoutException(message)

    def _stack_delete(self, stack_identifier):
        try:
            self.client.stacks.delete(stack_identifier)
        except heat_exceptions.HTTPNotFound:
            pass
        self._wait_for_stack_status(
            stack_identifier, 'DELETE_COMPLETE',
            success_on_not_found=True)

    def update_stack(self, stack_identifier, template, environment=None,
                     files=None):
        env = environment or {}
        env_files = files or {}
        stack_name = stack_identifier.split('/')[0]
        self.client.stacks.update(
            stack_id=stack_identifier,
            stack_name=stack_name,
            template=template,
            files=env_files,
            disable_rollback=True,
            parameters={},
            environment=env
        )
        self._wait_for_stack_status(stack_identifier, 'UPDATE_COMPLETE')

    def assert_resource_is_a_stack(self, stack_identifier, res_name):
        rsrc = self.client.resources.get(stack_identifier, res_name)
        nested_link = [l for l in rsrc.links if l['rel'] == 'nested']
        nested_href = nested_link[0]['href']
        nested_id = nested_href.split('/')[-1]
        nested_identifier = '/'.join(nested_href.split('/')[-2:])
        self.assertEqual(rsrc.physical_resource_id, nested_id)

        nested_stack = self.client.stacks.get(nested_id)
        nested_identifier2 = '%s/%s' % (nested_stack.stack_name,
                                        nested_stack.id)
        self.assertEqual(nested_identifier, nested_identifier2)
        parent_id = stack_identifier.split("/")[-1]
        self.assertEqual(parent_id, nested_stack.parent)
        return nested_identifier

    def list_resources(self, stack_identifier):
        resources = self.client.resources.list(stack_identifier)
        return dict((r.resource_name, r.resource_type) for r in resources)

    def stack_create(self, stack_name=None, template=None, files=None,
                     parameters=None, environment=None,
                     expected_status='CREATE_COMPLETE'):
        name = stack_name or self._stack_rand_name()
        templ = template or self.template
        templ_files = files or {}
        params = parameters or {}
        env = environment or {}
        self.client.stacks.create(
            stack_name=name,
            template=templ,
            files=templ_files,
            disable_rollback=True,
            parameters=params,
            environment=env
        )
        self.addCleanup(self.client.stacks.delete, name)

        stack = self.client.stacks.get(name)
        stack_identifier = '%s/%s' % (name, stack.id)
        self._wait_for_stack_status(stack_identifier, expected_status)
        return stack_identifier

    def stack_adopt(self, stack_name=None, files=None,
                    parameters=None, environment=None, adopt_data=None,
                    wait_for_status='ADOPT_COMPLETE'):
        name = stack_name or self._stack_rand_name()
        templ_files = files or {}
        params = parameters or {}
        env = environment or {}
        self.client.stacks.create(
            stack_name=name,
            files=templ_files,
            disable_rollback=True,
            parameters=params,
            environment=env,
            adopt_stack_data=adopt_data,
        )
        self.addCleanup(self.client.stacks.delete, name)

        stack = self.client.stacks.get(name)
        stack_identifier = '%s/%s' % (name, stack.id)
        self._wait_for_stack_status(stack_identifier, wait_for_status)
        return stack_identifier
