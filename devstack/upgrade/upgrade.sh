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

# Locate heat devstack plugin, the directory above the
# grenade plugin.
HEAT_DEVSTACK_DIR=$(dirname $(dirname $0))

# Duplicate some setup bits from target DevStack
source $TARGET_DEVSTACK_DIR/functions
source $TARGET_DEVSTACK_DIR/stackrc
source $TARGET_DEVSTACK_DIR/lib/tls
source $TARGET_DEVSTACK_DIR/lib/stack
source $TARGET_DEVSTACK_DIR/lib/apache
source $TARGET_DEVSTACK_DIR/lib/rpc_backend

# Get heat functions from devstack plugin
source $HEAT_DEVSTACK_DIR/lib/heat

# Print the commands being run so that we can see the command that triggers
# an error.  It is also useful for following allowing as the install occurs.
set -o xtrace

# Save current config files for posterity
[[ -d $SAVE_DIR/etc.heat ]] || cp -pr $HEAT_CONF_DIR $SAVE_DIR/etc.heat

# Install the target heat
source $HEAT_DEVSTACK_DIR/plugin.sh stack install

# Change transport-url in the host which runs upgrade script (primary)
if [[ "${HOST_TOPOLOGY}" == "multinode" ]]; then
    vhost="newvhost"
    rpc_backend_add_vhost $vhost
    iniset_rpc_backend heat $HEAT_CONF DEFAULT $vhost
fi

# calls upgrade-heat for specific release
upgrade_project heat $RUN_DIR $BASE_DEVSTACK_BRANCH $TARGET_DEVSTACK_BRANCH

# Simulate init_heat()
HEAT_BIN_DIR=$(dirname $(which heat-manage))
$HEAT_BIN_DIR/heat-manage --config-file $HEAT_CONF db_sync || die $LINENO "DB sync error"

# Start Heat
start_heat

# Don't succeed unless the services come up
# Truncating some service names to 11 characters
ensure_services_started heat-api heat-engine heat-api-cf

set +o xtrace
echo "*********************************************************************"
echo "SUCCESS: End $0"
echo "*********************************************************************"
