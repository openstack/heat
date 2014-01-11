================================
Building the user and admin docs
================================

This documentation should eventually end up in the OpenStack documentation
repositories `api-site` and `openstack-manuals`.

Dependencies
============

on Ubuntu:

  sudo apt-get install maven

on Fedora Core:

  sudo yum install maven

Use `mvn`
=========

Build the REST API reference manual:

  cd api-ref
  mvn clean generate-sources

Build the Heat admin guide:

  cd heat-admin
  mvn clean generate-sources

