===========
heat-engine
===========

.. program:: heat-engine

SYNOPSIS
========
``heat-engine [options]``

DESCRIPTION
===========
Heat is the heat project server with an internal api called by the heat-api.

INVENTORY
=========
The heat engine does all the orchestration work and is the layer in which
the resource integration is implemented.

OPTIONS
=======
.. cmdoption:: --config-file

  Path to a config file to use. Multiple config files can be specified, with
  values in later files taking precedence.


.. cmdoption:: --config-dir

  Path to a config directory to pull .conf files from. This file set is
  sorted, so as to provide a predictable parse order if individual options are
  over-ridden. The set is parsed after the file(s), if any, specified via 
  --config-file, hence over-ridden options in the directory take precedence.

FILES
========

* /etc/heat/heat.conf
