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

Heat and Devstack
=================
Heat is fully integrated into DevStack. This is a convenient way to try out or develop heat alongside the current development state of all the other OpenStack projects. Heat on DevStack works on both Ubuntu and Fedora.

These instructions assume you already have a working DevStack installation which can launch basic instances.

Configure DevStack to enable Heat
---------------------------------
Heat is configured by default on devstack for Icehouse and Juno releases.
Newer versions of OpenStack require enabling heat services in devstack
`local.conf`.

Add the following to `[[local|localrc]]` section of `local.conf`::

  [[local|localrc]]

  #Enable heat services
  enable_service h-eng h-api h-api-cfn h-api-cw

It would also be useful to automatically download and register
a VM image that Heat can launch. To do that add the following to your
devstack `localrc`::

    IMAGE_URLS+=",http://cloud.fedoraproject.org/fedora-20.x86_64.qcow2"

URLs for any cloud image may be specified, but fedora images from F20 contain the heat-cfntools package which is required for some heat functionality.

That is all the configuration that is required. When you run `./stack.sh` the Heat processes will be launched in `screen` with the labels prefixed with `h-`.

Configure DevStack to enable Ceilometer (if using Alarms)
---------------------------------------------------------
To use Ceilometer Alarms you need to enable Ceilometer in devstack.
Adding the following lines to your `localrc` file will enable the ceilometer services::

    CEILOMETER_BACKEND=mongo
    enable_service ceilometer-acompute ceilometer-acentral ceilometer-collector ceilometer-api
    enable_service ceilometer-alarm-notifier ceilometer-alarm-evaluator

Configure Devstack to enable OSprofiler
---------------------------------------

Add the profiler notifier to your Ceilometer to your config::

  CEILOMETER_NOTIFICATION_TOPICS=notifications,profiler

Enable the profiler in /etc/heat/heat.conf::

  $ echo -e "[profiler]\nprofiler_enabled = True\ntrace_sqlalchemy = True\n" >> /etc/heat/heat.conf

Change the default hmac_key in /etc/heat/api-paste.ini::

  $ sed -i "s/hmac_keys =.*/hmac_keys = SECRET_KEY/" /etc/heat/api-paste.ini

Run any command with --profile SECRET_KEY::

  $ heat --profile SECRET_KEY stack-list
  # it will print <Trace ID>

Get pretty HTML with traces::

  $ osprofiler trace show --html <Profile ID>

Note that osprofiler should be run with the admin user name & tenant.


Confirming Heat is responding
-----------------------------

Before any Heat commands can be run, the authentication environment
needs to be loaded::

    source openrc

You can confirm that Heat is running and responding
with this command::

    heat stack-list

This should return an empty line

Preparing Nova for running stacks
---------------------------------

Enabling Heat in devstack will replace the default Nova flavors with
flavors that the Heat example templates expect. You can see what
those flavors are by running::

    nova flavor-list

Heat needs to launch instances with a keypair, so we need
to generate one::

    nova keypair-add heat_key > heat_key.priv
    chmod 600 heat_key.priv

Launching a stack
-----------------
Now lets launch a stack, using an example template from the heat-templates repository::

    heat stack-create teststack -u
    http://git.openstack.org/cgit/openstack/heat-templates/plain/hot/F20/WordPress_Native.yaml -P key_name=heat_key -P image_id=Fedora-x86_64-20-20131211.1-sda

Which will respond::

    +--------------------------------------+-----------+--------------------+----------------------+
    | ID                                   | Name      | Status             | Created              |
    +--------------------------------------+-----------+--------------------+----------------------+
    | (uuid)                               | teststack | CREATE_IN_PROGRESS | (timestamp)          |
    +--------------------------------------+-----------+--------------------+----------------------+


List stacks
~~~~~~~~~~~
List the stacks in your tenant::

    heat stack-list

List stack events
~~~~~~~~~~~~~~~~~

List the events related to a particular stack::

   heat event-list teststack

Describe the wordpress stack
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Show detailed state of a stack::

   heat stack-show teststack

Note: After a few seconds, the stack_status should change from IN_PROGRESS to CREATE_COMPLETE.

Verify instance creation
~~~~~~~~~~~~~~~~~~~~~~~~
Because the software takes some time to install from the repository, it may be a few minutes before the Wordpress instance is in a running state.

Point a web browser at the location given by the WebsiteURL Output as shown by heat stack-show teststack::

    wget ${WebsiteURL}

Delete the instance when done
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Note: The list operation will show no running stack.::

    heat stack-delete teststack
    heat stack-list
