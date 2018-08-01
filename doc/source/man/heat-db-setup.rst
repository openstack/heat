=============
heat-db-setup
=============

.. program:: heat-db-setup


SYNOPSIS
========

``heat-db-setup [COMMANDS] [OPTIONS]``


DESCRIPTION
===========
heat-db-setup is a tool which configures the local MySQL database for
heat. Typically distro-specific tools would provide this functionality
so please read the distro-specific documentation for configuring heat.


COMMANDS
========

``rpm``

  Indicate the distribution is a RPM packaging based distribution.

``deb``

  Indicate the distribution is a DEB packaging based distribution.


OPTIONS
=======

.. cmdoption:: -h, --help

  Print usage information.

.. cmdoption:: -p, --password

  Specify the password for the 'heat' MySQL user that the script will use to
  connect to the 'heat' MySQL database. By default, the password 'heat' will
  be used.

.. cmdoption:: -r, --rootpw

  Specify the root MySQL password. If the script installs the MySQL server,
  it will set the root password to this value instead of prompting for a
  password. If the MySQL server is already installed, this password will be
  used to connect to the database instead of having to prompt for it.

.. cmdoption:: -y, --yes

  In cases where the script would normally ask for confirmation before doing
  something, such as installing mysql-server, just assume yes. This is useful
  if you want to run the script non-interactively.

EXAMPLES
========

  heat-db-setup rpm -p heat_password -r mysql_pwd -y

  heat-db-setup deb -p heat_password -r mysql_pwd -y

  heat-db-setup rpm

BUGS
====

Heat bugs are managed through StoryBoard
`OpenStack Heat Stories <https://storyboard.openstack.org/#!/project/989>`__
