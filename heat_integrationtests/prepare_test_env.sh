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

# This script creates required cloud resources and sets test options
# in heat_integrationtests.conf.
# Credentials are required for creating nova flavors and glance images.

set -x

DEST=${DEST:-/opt/stack/new}

source $DEST/devstack/inc/ini-config

cd $DEST/heat/heat_integrationtests

# Register the flavor for booting test servers
iniset heat_integrationtests.conf DEFAULT instance_type m1.heat_int
nova flavor-create m1.heat_int 452 512 0 1

iniset heat_integrationtests.conf DEFAULT image_ref Fedora-x86_64-20-20140618-sda
iniset heat_integrationtests.conf DEFAULT minimal_image_ref cirros-0.3.2-x86_64-uec

cat heat_integrationtests.conf