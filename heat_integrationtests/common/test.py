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

import os
import random
import re
import subprocess
import time

import fixtures
from heatclient import exc as heat_exceptions
from keystoneauth1 import exceptions as kc_exceptions
from oslo_log import log as logging
from oslo_utils import timeutils
import six
from six.moves import urllib
import testscenarios
import testtools

from heat_integrationtests.common import clients
from heat_integrationtests.common import config
from heat_integrationtests.common import exceptions

LOG = logging.getLogger(__name__)
_LOG_FORMAT = "%(levelname)8s [%(name)s] %(message)s"


def call_until_true(duration, sleep_for, func, *args, **kwargs):
    """Call the function until it returns True or the duration elapsed.

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
        if func(*args, **kwargs):
            return True
        LOG.debug("Sleeping for %d seconds", sleep_for)
        time.sleep(sleep_for)
        now = time.time()
    return False


def rand_name(name=''):
    randbits = six.text_type(random.randint(1, 0x7fffffff))
    if name:
        return name + '-' + randbits
    else:
        return randbits


def requires_convergence(test_method):
    '''Decorator for convergence-only tests.

    The decorated test will be skipped when convergence is disabled.
    '''
    convergence_enabled = config.init_conf(
    ).heat_plugin.convergence_engine_enabled
    skipper = testtools.skipUnless(convergence_enabled,
                                   "Convergence-only tests are disabled")
    return skipper(test_method)


class HeatIntegrationTest(testscenarios.WithScenarios,
                          testtools.TestCase):

    def setUp(self):
        super(HeatIntegrationTest, self).setUp()

        self.conf = config.init_conf().heat_plugin

        self.assertIsNotNone(self.conf.auth_url,
                             'No auth_url configured')
        self.assertIsNotNone(self.conf.username,
                             'No username configured')
        self.assertIsNotNone(self.conf.password,
                             'No password configured')
        self.setup_clients(self.conf)
        self.useFixture(fixtures.FakeLogger(format=_LOG_FORMAT))
        self.updated_time = {}
        if self.conf.disable_ssl_certificate_validation:
            self.verify_cert = False
        else:
            self.verify_cert = self.conf.ca_file or True

    def setup_clients(self, conf, admin_credentials=False):
        self.manager = clients.ClientManager(conf, admin_credentials)
        self.identity_client = self.manager.identity_client
        self.orchestration_client = self.manager.orchestration_client
        self.compute_client = self.manager.compute_client
        self.network_client = self.manager.network_client
        self.volume_client = self.manager.volume_client
        self.object_client = self.manager.object_client

        self.client = self.orchestration_client

    def setup_clients_for_admin(self):
        self.setup_clients(self.conf, True)

    def check_connectivity(self, check_ip):
        def try_connect(ip):
            try:
                urllib.request.urlopen('http://%s/' % ip)
                return True
            except IOError:
                return False

        timeout = self.conf.connectivity_timeout
        elapsed_time = 0
        while not try_connect(check_ip):
            time.sleep(10)
            elapsed_time += 10
            if elapsed_time > timeout:
                raise exceptions.TimeoutException()

    def _log_console_output(self, servers=None):
        if not servers:
            servers = self.compute_client.servers.list()
        for server in servers:
            LOG.info('Console output for %s', server.id)
            LOG.info(server.get_console_output())

    def _load_template(self, base_file, file_name, sub_dir=None):
        sub_dir = sub_dir or ''
        filepath = os.path.join(os.path.dirname(os.path.realpath(base_file)),
                                sub_dir, file_name)
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

    def assign_keypair(self):
        if self.conf.keypair_name:
            self.keypair = None
            self.keypair_name = self.conf.keypair_name
        else:
            self.keypair = self.create_keypair()
            self.keypair_name = self.keypair.id

    @classmethod
    def _stack_rand_name(cls):
        return rand_name(cls.__name__)

    def _get_network(self, net_name=None):
        if net_name is None:
            net_name = self.conf.fixed_network_name
        networks = self.network_client.list_networks()
        for net in networks['networks']:
            if net['name'] == net_name:
                return net

    def is_service_available(self, service_type):
        try:
            self.identity_client.get_endpoint_url(
                service_type, self.conf.region)
        except kc_exceptions.EndpointNotFound:
            return False
        else:
            return True

    @staticmethod
    def _stack_output(stack, output_key, validate_errors=True):
        """Return a stack output value for a given key."""
        value = None
        for o in stack.outputs:
            if validate_errors and 'output_error' in o:
                # scan for errors in the stack output.
                raise ValueError(
                    'Unexpected output errors in %s : %s' % (
                        output_key, o['output_error']))
            if o['output_key'] == output_key:
                value = o['output_value']
        return value

    def _ping_ip_address(self, ip_address, should_succeed=True):
        cmd = ['ping', '-c1', '-w1', ip_address]

        def ping():
            proc = subprocess.Popen(cmd,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            proc.wait()
            return (proc.returncode == 0) == should_succeed

        return call_until_true(
            self.conf.build_timeout, 1, ping)

    def _wait_for_all_resource_status(self, stack_identifier,
                                      status, failure_pattern='^.*_FAILED$',
                                      success_on_not_found=False):
        for res in self.client.resources.list(stack_identifier):
            self._wait_for_resource_status(
                stack_identifier, res.resource_name,
                status, failure_pattern=failure_pattern,
                success_on_not_found=success_on_not_found)

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
                wait_for_action = status.split('_')[0]
                resource_action = res.resource_status.split('_')[0]
                if (resource_action == wait_for_action and
                        fail_regexp.search(res.resource_status)):
                    raise exceptions.StackResourceBuildErrorException(
                        resource_name=res.resource_name,
                        stack_identifier=stack_identifier,
                        resource_status=res.resource_status,
                        resource_status_reason=res.resource_status_reason)
            time.sleep(build_interval)

        message = ('Resource %s failed to reach %s status within '
                   'the required time (%s s).' %
                   (resource_name, status, build_timeout))
        raise exceptions.TimeoutException(message)

    def verify_resource_status(self, stack_identifier, resource_name,
                               status='CREATE_COMPLETE'):
        try:
            res = self.client.resources.get(stack_identifier, resource_name)
        except heat_exceptions.HTTPNotFound:
            return False
        return res.resource_status == status

    def _verify_status(self, stack, stack_identifier, status,
                       fail_regexp, is_action_cancelled=False):
        if stack.stack_status == status:
            # Handle UPDATE_COMPLETE/FAILED case: Make sure we don't
            # wait for a stale UPDATE_COMPLETE/FAILED status.
            if status in ('UPDATE_FAILED', 'UPDATE_COMPLETE'):
                if is_action_cancelled:
                    return True

                if self.updated_time.get(
                        stack_identifier) != stack.updated_time:
                    self.updated_time[stack_identifier] = stack.updated_time
                    return True
            elif status == 'DELETE_COMPLETE' and stack.deletion_time is None:
                # Wait for deleted_time to be filled, so that we have more
                # confidence the operation is finished.
                return False
            else:
                return True

        wait_for_action = status.split('_')[0]
        if (stack.action == wait_for_action and
                fail_regexp.search(stack.stack_status)):
            # Handle UPDATE_COMPLETE/UPDATE_FAILED case.
            if status in ('UPDATE_FAILED', 'UPDATE_COMPLETE'):
                if self.updated_time.get(
                        stack_identifier) != stack.updated_time:
                    self.updated_time[stack_identifier] = stack.updated_time
                    raise exceptions.StackBuildErrorException(
                        stack_identifier=stack_identifier,
                        stack_status=stack.stack_status,
                        stack_status_reason=stack.stack_status_reason)
            else:
                raise exceptions.StackBuildErrorException(
                    stack_identifier=stack_identifier,
                    stack_status=stack.stack_status,
                    stack_status_reason=stack.stack_status_reason)

    def _wait_for_stack_status(self, stack_identifier, status,
                               failure_pattern=None,
                               success_on_not_found=False,
                               signal_required=False,
                               resources_to_signal=None,
                               is_action_cancelled=False):
        """Waits for a Stack to reach a given status.

        Note this compares the full $action_$status, e.g
        CREATE_COMPLETE, not just COMPLETE which is exposed
        via the status property of Stack in heatclient
        """
        if failure_pattern:
            fail_regexp = re.compile(failure_pattern)
        elif 'FAILED' in status:
            # If we're looking for e.g CREATE_FAILED, COMPLETE is unexpected.
            fail_regexp = re.compile('^.*_COMPLETE$')
        else:
            fail_regexp = re.compile('^.*_FAILED$')
        build_timeout = self.conf.build_timeout
        build_interval = self.conf.build_interval

        start = timeutils.utcnow()
        while timeutils.delta_seconds(start,
                                      timeutils.utcnow()) < build_timeout:
            try:
                stack = self.client.stacks.get(stack_identifier,
                                               resolve_outputs=False)
            except heat_exceptions.HTTPNotFound:
                if success_on_not_found:
                    return
                elif not any(s in status for s in ['CREATE', 'ADOPT']):
                    # raise exception when stack not found, if it's not
                    # in create or adopt (which should be the only two possible
                    # reason that stack may not have been created yet)
                    raise
                # ignore this, as the resource may not have
                # been created yet
            else:
                if self._verify_status(stack, stack_identifier, status,
                                       fail_regexp, is_action_cancelled):
                    return
            if signal_required:
                self.signal_resources(resources_to_signal)
            time.sleep(build_interval)

        message = ('Stack %s failed to reach %s status within '
                   'the required time (%s s).' %
                   (stack_identifier, status, build_timeout))
        raise exceptions.TimeoutException(message)

    def _stack_delete(self, stack_identifier):
        try:
            self._handle_in_progress(self.client.stacks.delete,
                                     stack_identifier)
        except heat_exceptions.HTTPNotFound:
            pass
        self._wait_for_stack_status(
            stack_identifier, 'DELETE_COMPLETE',
            success_on_not_found=True)

    def _handle_in_progress(self, fn, *args, **kwargs):
        build_timeout = self.conf.build_timeout
        build_interval = self.conf.build_interval
        start = timeutils.utcnow()
        while timeutils.delta_seconds(start,
                                      timeutils.utcnow()) < build_timeout:
            try:
                fn(*args, **kwargs)
            except heat_exceptions.HTTPConflict as ex:
                # FIXME(sirushtim): Wait a little for the stack lock to be
                # released and hopefully, the stack should be usable again.
                if ex.error['error']['type'] != 'ActionInProgress':
                    raise ex

                time.sleep(build_interval)
            else:
                break

    def update_stack(self, stack_identifier, template=None, environment=None,
                     files=None, parameters=None, tags=None,
                     expected_status='UPDATE_COMPLETE',
                     disable_rollback=True,
                     existing=False):
        env = environment or {}
        env_files = files or {}
        parameters = parameters or {}

        self.updated_time[stack_identifier] = self.client.stacks.get(
            stack_identifier, resolve_outputs=False).updated_time

        self._handle_in_progress(
            self.client.stacks.update,
            stack_id=stack_identifier,
            template=template,
            files=env_files,
            disable_rollback=disable_rollback,
            parameters=parameters,
            environment=env,
            tags=tags,
            existing=existing)

        kwargs = {'stack_identifier': stack_identifier,
                  'status': expected_status}
        if expected_status in ['ROLLBACK_COMPLETE']:
            # To trigger rollback you would intentionally fail the stack
            # Hence check for rollback failures
            kwargs['failure_pattern'] = '^ROLLBACK_FAILED$'

        self._wait_for_stack_status(**kwargs)

    def cancel_update_stack(self, stack_identifier, rollback=True,
                            expected_status='ROLLBACK_COMPLETE'):

        stack_name = stack_identifier.split('/')[0]

        self.updated_time[stack_identifier] = self.client.stacks.get(
            stack_identifier, resolve_outputs=False).updated_time

        if rollback:
            self.client.actions.cancel_update(stack_name)
        else:
            self.client.actions.cancel_without_rollback(stack_name)

        kwargs = {'stack_identifier': stack_identifier,
                  'status': expected_status}
        if expected_status == 'UPDATE_FAILED':
            kwargs['is_action_cancelled'] = True

        if expected_status in ['ROLLBACK_COMPLETE']:
            # To trigger rollback you would intentionally fail the stack
            # Hence check for rollback failures
            kwargs['failure_pattern'] = '^ROLLBACK_FAILED$'

        self._wait_for_stack_status(**kwargs)

    def preview_update_stack(self, stack_identifier, template,
                             environment=None, files=None, parameters=None,
                             tags=None, disable_rollback=True,
                             show_nested=False):
        env = environment or {}
        env_files = files or {}
        parameters = parameters or {}

        return self.client.stacks.preview_update(
            stack_id=stack_identifier,
            template=template,
            files=env_files,
            disable_rollback=disable_rollback,
            parameters=parameters,
            environment=env,
            tags=tags,
            show_nested=show_nested
        )

    def assert_resource_is_a_stack(self, stack_identifier, res_name,
                                   wait=False):
        build_timeout = self.conf.build_timeout
        build_interval = self.conf.build_interval
        start = timeutils.utcnow()
        while timeutils.delta_seconds(start,
                                      timeutils.utcnow()) < build_timeout:
            time.sleep(build_interval)
            try:
                nested_identifier = self._get_nested_identifier(
                    stack_identifier, res_name)
            except Exception:
                # We may have to wait, if the create is in-progress
                if wait:
                    time.sleep(build_interval)
                else:
                    raise
            else:
                return nested_identifier

    def _get_nested_identifier(self, stack_identifier, res_name):
        rsrc = self.client.resources.get(stack_identifier, res_name)
        nested_link = [l for l in rsrc.links if l['rel'] == 'nested']
        nested_href = nested_link[0]['href']
        nested_id = nested_href.split('/')[-1]
        nested_identifier = '/'.join(nested_href.split('/')[-2:])
        self.assertEqual(rsrc.physical_resource_id, nested_id)

        nested_stack = self.client.stacks.get(nested_id, resolve_outputs=False)
        nested_identifier2 = '%s/%s' % (nested_stack.stack_name,
                                        nested_stack.id)
        self.assertEqual(nested_identifier, nested_identifier2)
        parent_id = stack_identifier.split("/")[-1]
        self.assertEqual(parent_id, nested_stack.parent)
        return nested_identifier

    def group_nested_identifier(self, stack_identifier,
                                group_name):
        # Get the nested stack identifier from a group resource
        rsrc = self.client.resources.get(stack_identifier, group_name)
        physical_resource_id = rsrc.physical_resource_id

        nested_stack = self.client.stacks.get(physical_resource_id,
                                              resolve_outputs=False)
        nested_identifier = '%s/%s' % (nested_stack.stack_name,
                                       nested_stack.id)
        parent_id = stack_identifier.split("/")[-1]
        self.assertEqual(parent_id, nested_stack.parent)
        return nested_identifier

    def list_group_resources(self, stack_identifier,
                             group_name, minimal=True):
        nested_identifier = self.group_nested_identifier(stack_identifier,
                                                         group_name)
        if minimal:
            return self.list_resources(nested_identifier)
        return self.client.resources.list(nested_identifier)

    def list_resources(self, stack_identifier, filter_func=None):
        resources = self.client.resources.list(stack_identifier)
        return dict((r.resource_name, r.resource_type) for r in resources
                    if (filter_func(r) if callable(filter_func) else True))

    def get_resource_stack_id(self, r):
        stack_link = [l for l in r.links if l.get('rel') == 'stack'][0]
        return stack_link['href'].split("/")[-1]

    def get_physical_resource_id(self, stack_identifier, resource_name):
        try:
            resource = self.client.resources.get(
                stack_identifier, resource_name)
            return resource.physical_resource_id
        except Exception:
            raise Exception('Resource (%s) not found in stack (%s)!' %
                            (stack_identifier, resource_name))

    def get_stack_output(self, stack_identifier, output_key,
                         validate_errors=True):
        stack = self.client.stacks.get(stack_identifier)
        return self._stack_output(stack, output_key, validate_errors)

    def check_input_values(self, group_resources, key, value):
        # Check inputs for deployment and derived config
        for r in group_resources:
            d = self.client.software_deployments.get(
                r.physical_resource_id)
            self.assertEqual({key: value}, d.input_values)
            c = self.client.software_configs.get(
                d.config_id)
            foo_input_c = [i for i in c.inputs if i.get('name') == key][0]
            self.assertEqual(value, foo_input_c.get('value'))

    def signal_resources(self, resources):
        # Signal all IN_PROGRESS resources
        for r in resources:
            if 'IN_PROGRESS' in r.resource_status:
                stack_id = self.get_resource_stack_id(r)
                self.client.resources.signal(stack_id, r.resource_name)

    def stack_create(self, stack_name=None, template=None, files=None,
                     parameters=None, environment=None, tags=None,
                     expected_status='CREATE_COMPLETE',
                     disable_rollback=True, enable_cleanup=True,
                     environment_files=None, timeout=None):
        name = stack_name or self._stack_rand_name()
        templ = template or self.template
        templ_files = files or {}
        params = parameters or {}
        env = environment or {}
        timeout_mins = timeout or self.conf.build_timeout
        self.client.stacks.create(
            stack_name=name,
            template=templ,
            files=templ_files,
            disable_rollback=disable_rollback,
            parameters=params,
            environment=env,
            tags=tags,
            environment_files=environment_files,
            timeout_mins=timeout_mins
        )
        if enable_cleanup:
            self.addCleanup(self._stack_delete, name)

        stack = self.client.stacks.get(name, resolve_outputs=False)
        stack_identifier = '%s/%s' % (name, stack.id)
        kwargs = {'stack_identifier': stack_identifier,
                  'status': expected_status}
        if expected_status:
            if expected_status in ['ROLLBACK_COMPLETE']:
                # To trigger rollback you would intentionally fail the stack
                # Hence check for rollback failures
                kwargs['failure_pattern'] = '^ROLLBACK_FAILED$'
            self._wait_for_stack_status(**kwargs)
        return stack_identifier

    def stack_adopt(self, stack_name=None, files=None,
                    parameters=None, environment=None, adopt_data=None,
                    wait_for_status='ADOPT_COMPLETE'):
        if (self.conf.skip_test_stack_action_list and
                'ADOPT' in self.conf.skip_test_stack_action_list):
            self.skipTest('Testing Stack adopt disabled in conf, skipping')
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
        self.addCleanup(self._stack_delete, name)
        stack = self.client.stacks.get(name, resolve_outputs=False)
        stack_identifier = '%s/%s' % (name, stack.id)
        self._wait_for_stack_status(stack_identifier, wait_for_status)
        return stack_identifier

    def stack_abandon(self, stack_id):
        if (self.conf.skip_test_stack_action_list and
                'ABANDON' in self.conf.skip_test_stack_action_list):
            self.addCleanup(self._stack_delete, stack_id)
            self.skipTest('Testing Stack abandon disabled in conf, skipping')
        info = self.client.stacks.abandon(stack_id=stack_id)
        return info

    def stack_snapshot(self, stack_id,
                       wait_for_status='SNAPSHOT_COMPLETE'):
        snapshot = self.client.stacks.snapshot(stack_id=stack_id)
        self._wait_for_stack_status(stack_id, wait_for_status)
        return snapshot['id']

    def stack_restore(self, stack_id, snapshot_id,
                      wait_for_status='RESTORE_COMPLETE'):
        self.client.stacks.restore(stack_id, snapshot_id)
        self._wait_for_stack_status(stack_id, wait_for_status)

    def stack_suspend(self, stack_identifier):
        if (self.conf.skip_test_stack_action_list and
                'SUSPEND' in self.conf.skip_test_stack_action_list):
            self.addCleanup(self._stack_delete, stack_identifier)
            self.skipTest('Testing Stack suspend disabled in conf, skipping')
        self._handle_in_progress(self.client.actions.suspend, stack_identifier)
        # improve debugging by first checking the resource's state.
        self._wait_for_all_resource_status(stack_identifier,
                                           'SUSPEND_COMPLETE')
        self._wait_for_stack_status(stack_identifier, 'SUSPEND_COMPLETE')

    def stack_resume(self, stack_identifier):
        if (self.conf.skip_test_stack_action_list and
                'RESUME' in self.conf.skip_test_stack_action_list):
            self.addCleanup(self._stack_delete, stack_identifier)
            self.skipTest('Testing Stack resume disabled in conf, skipping')
        self._handle_in_progress(self.client.actions.resume, stack_identifier)
        # improve debugging by first checking the resource's state.
        self._wait_for_all_resource_status(stack_identifier,
                                           'RESUME_COMPLETE')
        self._wait_for_stack_status(stack_identifier, 'RESUME_COMPLETE')

    def wait_for_event_with_reason(self, stack_identifier, reason,
                                   rsrc_name=None, num_expected=1):
        build_timeout = self.conf.build_timeout
        build_interval = self.conf.build_interval
        start = timeutils.utcnow()
        while timeutils.delta_seconds(start,
                                      timeutils.utcnow()) < build_timeout:
            try:
                rsrc_events = self.client.events.list(stack_identifier,
                                                      resource_name=rsrc_name)
            except heat_exceptions.HTTPNotFound:
                LOG.debug("No events yet found for %s", rsrc_name)
            else:
                matched = [e for e in rsrc_events
                           if e.resource_status_reason == reason]
                if len(matched) == num_expected:
                    return matched
            time.sleep(build_interval)

    def check_autoscale_complete(self, stack_id, expected_num, parent_stack,
                                 group_name):
        res_list = self.client.resources.list(stack_id)
        all_res_complete = all(res.resource_status in ('UPDATE_COMPLETE',
                                                       'CREATE_COMPLETE')
                               for res in res_list)
        all_res = len(res_list) == expected_num
        if all_res and all_res_complete:
            metadata = self.client.resources.metadata(parent_stack, group_name)
            return not metadata.get('scaling_in_progress')
        return False
