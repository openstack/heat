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

localconf=$BASE/new/devstack/local.conf

echo -e '[[post-config|$HEAT_CONF]]\n[DEFAULT]\n' >> $localconf

if [ "$DISABLE_CONVERGENCE" == "true" ] ; then
    echo -e 'convergence_engine=false\n' >> $localconf
fi

echo -e 'stack_scheduler_hints=true\n' >> $localconf
echo -e 'hidden_stack_tags=hidden\n' >> $localconf
echo -e 'encrypt_parameters_and_properties=True\n' >> $localconf
echo -e 'logging_exception_prefix=%(asctime)s.%(msecs)03d %(process)d TRACE %(name)s %(instance)s\n' >> $localconf

echo -e '[heat_api]\nworkers=2\n' >> $localconf
echo -e '[heat_api_cfn]\nworkers=2\n' >> $localconf

echo -e '[cache]\nenabled=True\n' >> $localconf

echo -e '[eventlet_opts]\nclient_socket_timeout=120\n' >> $localconf

echo -e '[oslo_messaging_notifications]\ndriver=messagingv2\n' >> $localconf

echo "[[local|localrc]]" >> $localconf

# NOTE(ianw) OpenDev infra only keeps the latest two Fedora's
# around; prefer the mirror but allow fallback
if [[ -e /etc/ci/mirror_info.sh ]]; then
    source /etc/ci/mirror_info.sh
fi
HEAT_TEST_FEDORA_IMAGE_UPSTREAM=https://download.fedoraproject.org/pub/fedora/linux
HEAT_TEST_FEDORA_IMAGE_PATH=releases/36/Cloud/x86_64/images/Fedora-Cloud-Base-36-1.5.x86_64.qcow2
if curl --output /dev/null --silent --head --fail "${NODEPOOL_FEDORA_MIRROR}/${HEAT_TEST_FEDORA_IMAGE_PATH}"; then
    echo "IMAGE_URLS+=${NODEPOOL_FEDORA_MIRROR}/${HEAT_TEST_FEDORA_IMAGE_PATH}" >> $localconf
else
    echo "IMAGE_URLS+=${HEAT_TEST_FEDORA_IMAGE_UPSTREAM}/${HEAT_TEST_FEDORA_IMAGE_PATH}" >> $localconf
fi

echo "CEILOMETER_PIPELINE_INTERVAL=60" >> $localconf
echo "HEAT_ENABLE_ADOPT_ABANDON=True" >> $localconf
