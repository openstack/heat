========================================
Running Heat API services in HTTP Server
========================================

Since the Liberty release Heat has packaged a set of wsgi script entrypoints
that enables users to run api services with a real web server like Apache
HTTP Server (httpd).

There are several patterns for deployment. This doc shows some common ways of
deploying api services with httpd.

mod-wsgi
--------

This deployment method is possible since Liberty release.

The httpd/files directory contains sample files that can be changed and
copied to the appropriate location in your httpd server.

On Debian/Ubuntu systems it is::

    /etc/apache2/sites-available/heat-api.conf
    /etc/apache2/sites-available/heat-api-cfn.conf

On Red Hat based systems it is::

    /etc/httpd/conf.d/uwsgi-heat-api.conf
    /etc/httpd/conf.d/uwsgi-heat-api-cfn.conf

uwsgi
-----

In this deployment method we use uwsgi as a web server bound to a random local
port. Then we configure apache using mod_proxy to forward all incoming requests
on the specified endpoint to that local webserver. This has the advantage of
letting apache manage all inbound http connections, and uwsgi manage running
the python code. It also means when we make changes to Heat api code or
configuration, we don't need to restart all of apache (which may be running
other services too) and just need to restart the local uwsgi daemons.

The httpd/files directory contains sample files for configuring httpd to run
Heat api services under uwsgi in this configuration. To use the sample configs
simply copy `uwsgi-heat-api.conf` and `uwsgi-heat-api-cfn.conf` to the
appropriate location for your web server.

On Debian/Ubuntu systems it is::

    /etc/apache2/sites-available/uwsgi-heat-api.conf
    /etc/apache2/sites-available/uwsgi-heat-api-cfn.conf

On Red Hat based systems it is::

    /etc/httpd/conf.d/uwsgi-heat-api.conf
    /etc/httpd/conf.d/uwsgi-heat-api-cfn.conf

Enable mod_proxy by running ``sudo a2enmod proxy``

Then on Ubuntu/Debian systems enable the site by creating a symlink from the
file in ``sites-available`` to ``sites-enabled``. (This is not required on
Red Hat based systems)::

    ln -s /etc/apache2/sites-available/uwsgi-heat-api.conf /etc/apache2/sites-enabled
    ln -s /etc/apache2/sites-available/uwsgi-heat-api-cfn.conf /etc/apache2/sites-enabled

Start or restart httpd to pick up the new configuration.

Now we need to configure and start the uwsgi service. Copy the following
files to `/etc/heat`::

        heat-api-uwsgi.ini
        heat-api-cfn-uwsgi.ini

Update the files to match your system configuration (for example, you'll
want to set the number of processes and threads).

Install uwsgi and start the heat-api server using uwsgi::

    sudo pip install uwsgi
    uwsgi --ini /etc/heat/heat-api-uwsgi.ini
    uwsgi --ini /etc/heat/heat-api-cfn-uwsgi.ini

.. NOTE::

    In the sample configs some random ports are used, but this doesn't matter
    and is just a randomly selected number. This is not a contract on the port
    used for the local uwsgi daemon.


mod_proxy_uwsgi
'''''''''''''''

Instead of running uwsgi as a webserver listening on a local port and then
having Apache HTTP proxy all the incoming requests with mod_proxy, the
normally recommended way of deploying uwsgi with Apache httpd is to use
mod_proxy_uwsgi and set up a local socket file for uwsgi to listen on. Apache
will send the requests using the uwsgi protocol over this local socket
file.

The dsvm jobs in heat upstream gate uses this deployment method.

For more details on using mod_proxy_uwsgi see the `official docs
<https://uwsgi-docs.readthedocs.io/en/latest/Apache.html?highlight=mod_uwsgi_proxy#mod-proxy-uwsgi>`_.
