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

.. _create-a-stack:

Creating your first stack
=========================

Confirming you can access a Heat endpoint
-----------------------------------------

Before any Heat commands can be run, your cloud credentials need to be
sourced::

    $ source openrc

You can confirm that Heat is available with this command::

    $ heat stack-list

This should return an empty line

Preparing to create a stack
---------------------------

Your cloud will have different flavors and images available for
launching instances, you can discover what is available by running::

    $ openstack flavor list
    $ openstack image list


To allow you to SSH into instances launched by Heat, a keypair will be
generated::

    $ openstack keypair create heat_key > heat_key.priv
    $ chmod 600 heat_key.priv

Launching a stack
-----------------
Now lets launch a stack, using an example template from the heat-templates repository::

    $ heat stack-create -u http://git.openstack.org/cgit/openstack/heat-templates/plain/hot/F20/WordPress_Native.yaml -P key_name=heat_key -P image_id=my-fedora-image -P instance_type=m1.small teststack

Which will respond::

    +--------------------------------------+-----------+--------------------+----------------------+
    | ID                                   | Name      | Status             | Created              |
    +--------------------------------------+-----------+--------------------+----------------------+
    | (uuid)                               | teststack | CREATE_IN_PROGRESS | (timestamp)          |
    +--------------------------------------+-----------+--------------------+----------------------+

List stacks
~~~~~~~~~~~
List the stacks in your tenant::

    $ heat stack-list

List stack events
~~~~~~~~~~~~~~~~~
List the events related to a particular stack::

   $ heat event-list teststack

Describe the wordpress stack
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Show detailed state of a stack::

   $ heat stack-show teststack

Note: After a few seconds, the stack_status should change from ``IN_PROGRESS``
to ``CREATE_COMPLETE``.

Verify instance creation
~~~~~~~~~~~~~~~~~~~~~~~~
Because the software takes some time to install from the repository, it may be
a few minutes before the Wordpress instance is in a running state.

Point a web browser at the location given by the ``WebsiteURL`` output as shown
by ``heat output-show``::

    $ WebsiteURL=$(heat output-show --format raw teststack WebsiteURL)
    $ curl $WebsiteURL

Delete the instance when done
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Note: The list operation will show no running stack.::

    $ heat stack-delete teststack
    $ heat stack-list

You can explore other heat commands by refering to the
`Heat chapter
<http://docs.openstack.org/cli-reference/heat.html>`_
of the `OpenStack Command-Line Interface Reference
<http://docs.openstack.org/cli-reference/index.html>`_ then read
the :ref:`template-guide` and start authoring your own templates.
