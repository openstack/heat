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

# This script creates default tenant networks for the tests

set -x

source $DEST/devstack/openrc admin admin
PUB_SUBNET_ID=`neutron subnet-list | grep ' public-subnet ' | awk '{split($0,a,"|"); print a[2]}'`
ROUTER_GW_IP=`neutron port-list -c fixed_ips -c device_owner | grep router_gateway | awk -F '"' -v subnet_id="${PUB_SUBNET_ID//[[:space:]]/}" '$4 == subnet_id { print $8; }'`

# create a heat specific private network (default 'private' network has ipv6 subnet)
source $DEST/devstack/openrc demo demo
HEAT_PRIVATE_SUBNET_CIDR=10.0.5.0/24
neutron net-create heat-net
neutron subnet-create --name heat-subnet heat-net $HEAT_PRIVATE_SUBNET_CIDR
neutron router-interface-add router1 heat-subnet
sudo route add -net $HEAT_PRIVATE_SUBNET_CIDR gw $ROUTER_GW_IP
