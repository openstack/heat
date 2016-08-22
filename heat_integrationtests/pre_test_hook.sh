#!/bin/bash
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# This script is executed inside pre_test_hook function in devstack gate.

set -x

localrc_path=$BASE/new/devstack/localrc
localconf=$BASE/new/devstack/local.conf

echo "CEILOMETER_PIPELINE_INTERVAL=60" >> $localrc_path
echo "HEAT_ENABLE_ADOPT_ABANDON=True" >> $localrc_path

echo -e '[[post-config|$HEAT_CONF]]\n[DEFAULT]\n' >> $localconf

if [ "$DISABLE_CONVERGENCE" == "true" ] ; then
    echo -e 'convergence_engine=false\n' >> $localconf
fi

echo -e 'stack_scheduler_hints=true\n' >> $localconf
echo -e 'notification_driver=messagingv2\n' >> $localconf
echo -e 'hidden_stack_tags=hidden\n' >> $localconf
echo -e 'encrypt_parameters_and_properties=True\n' >> $localconf
echo -e 'logging_exception_prefix=%(asctime)s.%(msecs)03d %(process)d TRACE %(name)s %(instance)s\n' >> $localconf
# Limit the number of connections, we're overflowing mysql
echo -e 'executor_thread_pool_size=8\n' >> $localconf

echo -e '[heat_api]\nworkers=2\n' >> $localconf
echo -e '[heat_api_cfn]\nworkers=2\n' >> $localconf
echo -e '[heat_api_cloudwatch]\nworkers=2\n' >> $localconf

echo -e '[cache]\nenabled=True\n' >> $localconf

echo -e '[[post-config|/etc/neutron/neutron_vpnaas.conf]]\n' >> $localconf
echo -e '[service_providers]\nservice_provider=VPN:openswan:neutron_vpnaas.services.vpn.service_drivers.ipsec.IPsecVPNDriver:default\n' >> $localconf

# Use the lbaas v2 namespace driver for devstack integration testing since
# octavia uses nested vms.
if [[ $OVERRIDE_ENABLED_SERVICES =~ "q-lbaasv2" ]]
then
  echo "NEUTRON_LBAAS_SERVICE_PROVIDERV2=LOADBALANCERV2:Haproxy:neutron_lbaas.drivers.haproxy.plugin_driver.HaproxyOnHostPluginDriver:default" >> $localrc_path
fi
