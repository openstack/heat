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

source $TOP_DIR/openrc demo demo

# delete the network created
openstack router remove subnet router1 heat-subnet
openstack subnet delete heat-subnet
openstack network delete heat-net

source $TOP_DIR/openrc admin admin

# delete the flavors created
openstack flavor delete m1.heat_int
openstack flavor delete m1.heat_micro

# delete the image created
openstack image delete Fedora-Cloud-Base-29-1.2.x86_64
