..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

How to get heat to work with a remote OpenStack.
================================================

Say you have a remote/public install of OpenStack and you want to use
a local install of heat to talk to it. This can be handy when
developing, as the remote OpenStack can be kept stable and is not
effected by changes made to the development machine.

So lets say you have 2 machines:

 * “rock” ip == 192.168.1.88 (used for base OpenStack services)
 * “hack” ip == 192.168.1.77 (used for heat development)

Install your OpenStack as normal on “rock”.

In this example "hack" is used as the devstack to install heat on.
The localrc looked like this::

  HEAT_STANDALONE=True
  KEYSTONE_AUTH_HOST=192.168.1.88
  KEYSTONE_AUTH_PORT=35357
  KEYSTONE_AUTH_PROTOCOL=http
  KEYSTONE_SERVICE_HOST=$KEYSTONE_AUTH_HOST
  KEYSTONE_SERVICE_PORT=$KEYSTONE_AUTH_PORT
  KEYSTONE_SERVICE_PROTOCOL=$KEYSTONE_AUTH_PROTOCOL

  MY_PASSWORD=abetterpasswordthanthis
  DATABASE_PASSWORD=$MY_PASSWORD
  RABBIT_PASSWORD=$MY_PASSWORD

  disable_all_services
  # Alternative RPC backends are zeromq and rabbit
  ENABLED_SERVICES=qpid
  enable_service mysql heat h-api h-api-cfn h-api-cw h-eng

Then run your ./stack.sh as normal.

You then need a special environment (not devstack/openrc) to make this work.
go to your “rock” machine and get the tenant_id that you want to work
with::

  keystone tenant-list
  +----------------------------------+--------------------+---------+
  |                id                |        name        | enabled |
  +----------------------------------+--------------------+---------+
  | 6943e3ebad0d465387d05d73f8e0b3fc |       admin        |   True  |
  | b12482712e354dd3b9f64ce608ba20f3 |      alt_demo      |   True  |
  | bf03bf32e3884d489004ac995ff7a61c |        demo        |   True  |
  | c23ceb3bf5dd4f9692488855de99137b | invisible_to_admin |   True  |
  | c328c1f3b945487d859ed2f53dcf0fe4 |      service       |   True  |
  +----------------------------------+--------------------+---------+

Let's say you want “demo”.
Now make a file to store your new environment (heat.env).
::

  export HEAT_URL=http://192.168.1.77:8004/v1/bf03bf32e3884d489004ac995ff7a61c
  export OS_NO_CLIENT_AUTH=True
  export OS_USERNAME=admin
  export OS_TENANT_NAME=demo
  export OS_PASSWORD=abetterpasswordthanthis
  export OS_AUTH_URL=http://192.168.1.88:35357/v2.0/

Now you use this like::

  . heat.env
  heat stack-list

Note: remember to open up firewall ports on “rock” so that you can
access the OpenStack services.
