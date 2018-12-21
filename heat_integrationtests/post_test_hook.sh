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

# This script is executed inside post_test_hook function in devstack gate.

set -ex

export DEST=${DEST:-/opt/stack/new}
export TOP_DIR=${TOP_DIR:-/opt/stack/new/devstack}
sudo -E $DEST/heat/heat_integrationtests/prepare_test_env.sh
sudo -E $DEST/heat/heat_integrationtests/prepare_test_network.sh

cd $DEST/tempest
sudo tox -evenv-tempest -- stestr --test-path=$DEST/heat/heat_integrationtests --top-dir=$DEST/heat --group_regex='heat_tempest_plugin\.tests\.api\.test_heat_api[._]([^_]+)' run

sudo -E $DEST/heat/heat_integrationtests/cleanup_test_env.sh
