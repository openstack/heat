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

Commands are ``db_version``, ``db_sync``, ``purge_deleted``,
``migrate_convergence_1``, ``migrate_properties_data``, and
``service``. Detailed descriptions are below.

``heat-manage db_version``

    Print out the db schema version.

``heat-manage db_sync``

    Sync the database up to the most recent version.

``heat-manage purge_deleted [-g {days,hours,minutes,seconds}] [-p project_id] [age]``

    Purge db entries marked as deleted and older than [age]. When project_id
    argument is provided, only entries belonging to this project will be purged.

``heat-manage migrate_properties_data``

    Migrates properties data from the legacy locations in the db
    (resource.properties_data and event.resource_properties) to the
    modern location, the resource_properties_data table.

``heat-manage migrate_convergence_1 [stack_id]``

    Migrates [stack_id] from non-convergence to convergence. This requires running
    convergence enabled heat engine(s) and can't be done when they are offline.

``heat-manage service list``

    Shows details for all currently running heat-engines.

``heat-manage service clean``

    Clean dead engine records.

``heat-manage --version``

  Shows program's version number and exit. The output could be empty if
  the distribution didn't specify any version information.

FILES
=====

The /etc/heat/heat.conf file contains global options which can be
used to configure some aspects of heat-manage, for example the DB
connection and logging.

BUGS
====

Heat bugs are managed through StoryBoard
`OpenStack Heat Stories <https://storyboard.openstack.org/#!/project/989>`__
