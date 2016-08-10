#!/bin/bash
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
# ``upgrade-heat``

echo "*********************************************************************"
echo "Begin $0"
echo "*********************************************************************"

# Clean up any resources that may be in use
cleanup() {
    set +o errexit

    echo "*********************************************************************"
    echo "ERROR: Abort $0" >&2
    echo "*********************************************************************"

    # Kill ourselves to signal any calling process
    trap 2; kill -2 $$
}

trap cleanup SIGHUP SIGINT SIGTERM

# Keep track of the grenade directory
RUN_DIR=$(cd $(dirname "$0") && pwd)

# Source params
source $GRENADE_DIR/grenaderc

# Import common functions
source $GRENADE_DIR/functions

# This script exits on an error so that errors don't compound and you see
# only the first error that occurred.
set -o errexit

# Upgrade Heat
# ============

# Duplicate some setup bits from target DevStack
source $TARGET_DEVSTACK_DIR/functions
source $TARGET_DEVSTACK_DIR/stackrc
source $TARGET_DEVSTACK_DIR/lib/tls
source $TARGET_DEVSTACK_DIR/lib/stack
source $TARGET_DEVSTACK_DIR/lib/apache
source $TARGET_DEVSTACK_DIR/lib/heat

# Print the commands being run so that we can see the command that triggers
# an error.  It is also useful for following allowing as the install occurs.
set -o xtrace

# Save current config files for posterity
[[ -d $SAVE_DIR/etc.heat ]] || cp -pr $HEAT_CONF_DIR $SAVE_DIR/etc.heat

# install_heat()
stack_install_service heat
install_heatclient
install_heat_other

# calls upgrade-heat for specific release
upgrade_project heat $RUN_DIR $BASE_DEVSTACK_BRANCH $TARGET_DEVSTACK_BRANCH

# Simulate init_heat()
create_heat_cache_dir

HEAT_BIN_DIR=$(dirname $(which heat-manage))
$HEAT_BIN_DIR/heat-manage --config-file $HEAT_CONF db_sync || die $LINENO "DB sync error"

# Start Heat
start_heat

# Don't succeed unless the services come up
ensure_services_started heat-api heat-engine heat-api-cloudwatch heat-api-cfn

set +o xtrace
echo "*********************************************************************"
echo "SUCCESS: End $0"
echo "*********************************************************************"
