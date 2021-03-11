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

Heat and DevStack
=================
Heat is fully integrated into DevStack. This is a convenient way to try out or
develop heat alongside the current development state of all the other
OpenStack projects. Heat on DevStack works on both Ubuntu and Fedora.

These instructions assume you already have a working DevStack installation
which can launch basic instances.

Configure DevStack to enable heat
---------------------------------
Heat is configured by default on devstack for Icehouse and Juno releases.

Newer versions of OpenStack require enabling heat services in devstack
`local.conf`. Add the following to `[[local|localrc]]` section of
`local.conf`::

  [[local|localrc]]

  #Enable heat services
  enable_service h-eng h-api h-api-cfn h-api-cw

Since Newton release, heat is available as a devstack plugin. To enable the
plugin add the following to the `[[local|localrc]]` section of `local.conf`::

  [[local|localrc]]

  #Enable heat plugin
  enable_plugin heat https://opendev.org/openstack/heat

To use stable branches, make sure devstack is on that branch,
and specify the branch name to enable_plugin, for example::

  enable_plugin heat https://opendev.org/openstack/heat stable/newton

It would also be useful to automatically download and register
a VM image that heat can launch. To do that add the following to
`[[local|localrc]]` section of `local.conf`::

    IMAGE_URL_SITE="https://download.fedoraproject.org"
    IMAGE_URL_PATH="/pub/fedora/linux/releases/33/Cloud/x86_64/images/"
    IMAGE_URL_FILE="Fedora-Cloud-Base-33-1.2.x86_64.qcow2"
    IMAGE_URLS+=","$IMAGE_URL_SITE$IMAGE_URL_PATH$IMAGE_URL_FILE

URLs for any cloud image may be specified, but fedora images from F20 contain
the heat-cfntools package which is required for some heat functionality.

That is all the configuration that is required. When you run `./stack.sh` the
heat processes will be launched in `screen` with the labels prefixed with `h-`.

Configure DevStack to enable ceilometer and aodh (if using alarms)
------------------------------------------------------------------
To use aodh alarms you need to enable ceilometer and aodh in devstack.
Adding the following lines to `[[local|localrc]]` section of `local.conf`
will enable the services::

    CEILOMETER_BACKEND=mongodb
    enable_plugin ceilometer https://opendev.org/openstack/ceilometer
    enable_plugin aodh https://opendev.org/openstack/aodh

Configure DevStack to enable OSprofiler
---------------------------------------

Adding the following line to `[[local|localrc]]` section of `local.conf`
will add the profiler notifier to your ceilometer::

  CEILOMETER_NOTIFICATION_TOPICS=notifications,profiler

Enable the profiler in /etc/heat/heat.conf::

  $ echo -e "[profiler]\nenabled = True\n"\
  "trace_sqlalchemy = True\n"\
  "hmac_keys = SECRET_KEY\n"\
  >> /etc/heat/heat.conf

Run any command with --profile SECRET_KEY::

  $ heat --profile SECRET_KEY stack-list
  # it will print <Trace ID>

Get pretty HTML with traces::

  $ osprofiler trace show --html <Trace ID>

Note that osprofiler should be run with the admin user name & tenant.

Create a stack
--------------

Now that you have a working heat environment you can go to
:ref:`create-a-stack`.
