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

set -o errexit

source $GRENADE_DIR/grenaderc
source $GRENADE_DIR/functions

# We need base DevStack functions for this
source $BASE_DEVSTACK_DIR/functions
source $BASE_DEVSTACK_DIR/stackrc # needed for status directory
source $BASE_DEVSTACK_DIR/lib/tls
source $BASE_DEVSTACK_DIR/lib/apache

HEAT_DEVSTACK_DIR=$(dirname $(dirname $0))
source $HEAT_DEVSTACK_DIR/lib/heat

set -o xtrace

stop_heat

# stop cloudwatch service if running
# TODO(ramishra): Remove it after Queens
stop_cw_service

SERVICES_DOWN="heat-api heat-engine heat-api-cfn"

# sanity check that services are actually down
ensure_services_stopped $SERVICES_DOWN
