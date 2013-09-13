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

Building JEOS images for use with Heat
======================================
Heat's full functionality can only be used when launching cloud images that have
the heat-cfntools_ package installed.
This document describes some options for creating a heat-cfntools enabled image
for yourself.

.. _heat-cfntools: https://github.com/openstack/heat-cfntools

Building an image with diskimage-builder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
diskimage-builder_ is a tool for customizing cloud images.
tripleo-image-elements_ is a collection of diskimage-builder elements related
to the TripleO_ project. It includes an element for heat-cfntools which can be
used to create heat-enabled images.

.. _diskimage-builder: https://github.com/openstack/diskimage-builder
.. _tripleo-image-elements: https://github.com/openstack/tripleo-image-elements
.. _TripleO: https://wiki.openstack.org/wiki/TripleO

Fetch the tool and elements::

    git clone https://github.com/openstack/diskimage-builder.git
    git clone https://github.com/openstack/tripleo-image-elements.git

To create a heat-cfntools enabled image with the current release of Fedora x86_64::

    export ELEMENTS_PATH=tripleo-image-elements/elements
    diskimage-builder/bin/disk-image-create vm fedora heat-cfntools -a amd64 -o fedora-heat-cfntools

The image may then be pushed to glance, e.g::

    source ~/.openstack/keystonerc
    glance image-create --name fedora-heat-cfntools --is-public true --disk-format qcow2 --container-format bare < fedora-heat-cfntools.qcow2

To create a heat-cfntools enabled image with the current release of Ubuntu i386::

    export ELEMENTS_PATH=tripleo-image-elements/elements
    diskimage-builder/bin/disk-image-create vm ubuntu heat-cfntools -a i386 -o ubuntu-heat-cfntools

If you are creating your own images you should consider creating golden images
which contain all the packages required for the stacks that you launch. You can do
this by writing your own diskimage-builder elements and invoking those elements
in the call to disk-image-create.

This means that the resulting heat templates only need to modify configuration
files. This will speed stack launch time and reduce the risk of a transient
package download failure causing the stack launch to fail.

Building an image with Oz
~~~~~~~~~~~~~~~~~~~~~~~~~
Another approach to building a heat-cfntools enabled image is to use Oz wrapped in a convenience script.

The example below demonstrates how to build an F17 image, but there are Oz tdl templates for several other distributions provided in heat-templates/jeos

Get heat-templates
------------------

Clone the heat-templates repository from GitHub at ``git://github.com/openstack/heat-templates.git``


Note Oz does not work in virt on virt situations.  In this case, it is recommended that the prebuilt images are used.

Download OS install DVD and copy it to libvirt images location
--------------------------------------------------------------

::

  sudo cp Downloads/Fedora-17-x86_64-DVD.iso /var/lib/libvirt/images

Install Oz (RPM distros)
------------------------

We recommend cloning oz from the latest master.  Support for building guests based on recent distributions is not available in the version of Oz shipped with many distros.

On Fedora and other RPM-based distros::

    git clone -q https://github.com/clalancette/oz.git
    pushd oz
    rm -f ~/rpmbuild/RPMS/noarch/oz-*
    make rpm
    sudo yum -q -y localinstall ~/rpmbuild/RPMS/noarch/oz-*
    popd

Note: In the steps above, it's only necessary to be root for the yum localinstall, it's recommended not to be root while building the rpm.

Install Oz (DEB distros)
------------------------

We recommend cloning oz from the latest master.  The debian packaging is broken in older versions and support for building guests based on recent distributions is not available in the version of Oz shipped with many distros.

On Fedora and other RPM-based distros:


On Debian, Ubuntu and other deb based distros::

    git clone https://github.com/clalancette/oz.git
    cd oz
    make deb
    cd ..
    sudo dpkg -i oz_*_all.deb
    sudo apt-get -f install

Note: Select yes to "Create or update supermin appliance.".  This will rebuild the guestfs appliance to work with latest updates of Ubuntu.  Oz will not work properly without updating the guestfs appliance.


Configure libguestfs (required by Oz) to work in latest Ubuntu 12
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Some files shipped with Ubuntu 12 are incompatible with libguestfs
used by the image creation software Oz.  To allow heat-jeos to work
properly, run the following commands::

    sudo chmod 644 /boot/vmlinuz*
    sudo update-guestfs-appliance

Note: For more details see: http://permalink.gmane.org/gmane.comp.emulators.guestfs/1382
and http://libguestfs.org/guestfs-faq.1.html

Note: If you want to create F17 images, you may need a new libguestfs binary of version 1.18.0 or later.  Ubuntu Precise may not have this version yet.

You can use the Debian Wheezy version including the `guestfs shared library`_, the tools_ and the `python libraries`_.

.. _guestfs shared library: http://packages.debian.org/wheezy/amd64/libguestfs0/download
.. _tools: http://packages.debian.org/wheezy/amd64/libguestfs-tools/download
.. _python libraries: http://packages.debian.org/wheezy/amd64/python-guestfs/download


Create a JEOS with heat-jeos.sh script
--------------------------------------

heat-templates/tools contains a convenience wrapper for Oz which demonstrates how to create a JEOS::

    cd heat-templates/tools
    sudo ./heat-jeos.sh ../jeos/F17-x86_64-cfntools.tdl F17-x86_64-cfntools

Note: the second argument is the name as defined inside the TDL, so it may not necessarily match the filename

Note: ``heat-jeos.sh`` must be run as root in order to create the disk image.

Register the image with glance
------------------------------

On successful completion, the heat-jeos.sh script will generate a qcow2 image under /var/lib/libvirt/images/

The image may then be pushed to glance, e.g::

    source ~/.openstack/keystonerc
    glance add name=F17-x86_64-cfntools is_public=true disk_format=qcow2 container_format=bare < /var/lib/libvirt/images/F17-x86_64-cfntools.qcow2
