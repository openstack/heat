===========
heat-manage
===========

.. program:: heat-manage

SYNOPSIS
========
``heat-manage <action> [options]``

DESCRIPTION
===========
heat-manage helps manage heat specific database operations.


OPTIONS
=======

The standard pattern for executing a heat-manage command is:
``heat-manage <command> [<args>]``

Run with -h to see a list of available commands:
``heat-manage -h``

Commands are db_version, db_sync, purge_deleted and service. Detailed descriptions are below.


Heat Db version
~~~~~~~~~~~~~~~

``heat-manage db_version``

    Print out the db schema revision.

``heat-manage db_sync``

    Sync the database up to the most recent version.

``heat-manage purge_deleted [-g {days,hours,minutes,seconds}] [age]``

    Purge db entries marked as deleted and older than [age].

``heat-manage service list``

    Shows details for all currently running heat engines.

FILES
=====

The /etc/heat/heat.conf file contains global options which can be
used to configure some aspects of heat-manage, for example the DB
connection and logging.

BUGS
====

* Heat issues are tracked in Launchpad so you can view or report bugs here
  `OpenStack Heat Bugs <https://bugs.launchpad.net/heat>`__
