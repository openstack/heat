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

# Register the flavor for booting test servers
source /opt/stack/new/devstack/accrc/admin/admin
export HEAT_TEST_INSTANCE_TYPE=m1.heat_int
nova flavor-create $HEAT_TEST_INSTANCE_TYPE 452 512 0 1

export HEAT_TEST_IMAGE_REF=Fedora-x86_64-20-20140618-sda
export HEAT_TEST_MINIMAL_IMAGE_REF=cirros-0.3.2-x86_64-uec

source /opt/stack/new/devstack/accrc/demo/demo
cd /opt/stack/new/heat
sudo -E tox -eintegration
