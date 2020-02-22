.. highlight: yaml
   :linenothreshold: 5

.. _multi-clouds:

====================
Multi-Clouds support
====================

Start from Stein release (version 12.0.0), Heat support multi-clouds
orchestration. This document means to provide guideline for how to use
multi-clouds features, and what's the environment requirement.

.. note:: If you like to create a stack in multi-region environment,
  you don't need this feature at all. all you need to do is provide
  `region_name` under `context` property for :ref:`OS::Heat::Stack`.
  If you like to see information on how to provide SSL support for
  your multi-region environment, you can jump to `Use CA
  cert (Optional)`_ .

Requirements
~~~~~~~~~~~~

* **Barbican service** - For better security concerns, multi-cloud
  orchestration feature depends on Barbican service. So you have to make sure
  Barbican service is ready in your environment before you use this feature.

* **Access to remote Orchestration service** - Before you run your multi-cloud
  template. Make sure you're able to access to remote Orchestration service
  with correct endpoint information, legal access right, and ability to access
  to the remote site KeyStone, and Orchestration service API endpoint from
  local site. You need to make sure local Orchestration service is able to
  trigger and complete necessary API calls from local site to remote site. So we
  can complete stack actions without facing any access error.

* **Template complete resources/functions compatibility** - In your
  Orchestration template, you might want to use all kind of template functions
  or resource types as your template version and your Orchestration service
  allows. But please aware that once you plan to use Orchestration services
  across multiple OpenStack clouds, you have to also consider the
  compatibility. Make sure the template version and resource types are ready to
  use before you ask remote site to run it. If you accidentally provide wrong
  template version (which not provided in remote site), you will get error
  message from remote site which prevent you from actually create remote
  resources. But it's even better if we can just find such an error earlier.


Prepare
~~~~~~~

First of all, you need to put your remote cloud credential in a Barbican
secret. To build your own multi-clouds stack, you need to build a Barbican
secret first with most information for remote endpoint information.

Gathering credential information
--------------------------------

Before we start generating secret, let's talk about what credential format we
need. credential is a JSON format string contains two keys ``auth_type``, and
``auth``. ``auth_type``, and ``auth`` following auth plugin loader rules from
Keystone. You can find :keystoneauth-doc:`plugin options
<plugin-options.html>` and :keystoneauth-doc:`authentication plugins
<authentication-plugins.html#loading-plugins-by-name>` in keystoneauth
documents.

* **auth_type** - ``auth_type`` is a string for plugin name. Allows value like
  `v3applicationcredential`, `password`, `v3oidcclientcredentials`, etc. You
  need to provide `available plugins
  <plugin-options.html#available-plugins>`.

* **auth** - auth is a dictionary contains all parameters for plugins to
  perform authentication. You can find all valid parameter references from
  :keystoneauth-doc:`available plugins
  <plugin-options.html#available-plugins>` or get to all class path from
  :keystoneauth-doc:`plugin names
  <authentication-plugins.html#loading-plugins-by-name>` for more detail
  allowed value or trace plugin class from there.

As you can tell, all allowed authentication plugins for credentials follows
plugins keystoneauth rules. So once new change in keystoneauth, it will also
directly reflect credentials too.
Actually we just call keystoneauth to get plugin loader for remote
authentication plugins. So keep an eye on keystoneauth if you're using this
feature.

Validate your credential
------------------------

Now you have all your credential information ready, try to validate first if
you can. You can either directly test them :keystoneauth-doc:`via config
<plugin-options.html#using-plugins-via-config-file>`,
:keystoneauth-doc:`via CLI <plugin-options.html#using-plugins-via-cli>`,
or :keystoneauth-doc:`via keystoneauth sessions <using-sessions.html>`.

build credential secret
-----------------------

Once you're sure it's valid, we can start building the secret out. To build a
secret you just have to follow the standard
:python-barbicanclient-doc:`Barbican CLI <cli/cli_usage.html#secret-create>` or
API to store your secret.

The local site will read this secret to perform stack actions in remote site.
Let's give a quick example here:
Said you have two OpenStack cloud site A and site B.
If you need to control site B from site A, make sure you have a secret with
site B's access information in site A. If you also like to control site A from
site B, make sure you have a secret with site A's access information in site B.

.. code-block:: sh

  openstack secret store -n appcred --payload '{"auth_type": "v3applicationcredential", "auth": {"auth_url": "{Keystone_URL}", "application_credential_id": "{ID}", "application_credential_secret": "{SECRET}"}}'

.. note:: One common error for JSON format is to use single quote(`'`)
    instead of double quote (`"`) inner your JSON schema.

Create remote stacks
--------------------

Now, you have a secret id generated for your Barbican secret. Use that id as
input for template.

To create a remote stack, you can simply use an :ref:`OS::Heat::Stack` resource
in your template.

In resource properties, provide `credential_secret_id` (Barbican secret ID
from the secret we just builded for credential) under `context` property.

Here is an template example for you:

.. code-block:: yaml

  heat_template_version: rocky

  resources:
    stack_in_remote_cloud:
      type: OS::Heat::Stack
      properties:
        context:
          credential_secret_id: {$Your_Secret_ID}
        template: { get_file: "remote-app.yaml" }

And that's all you need to do. The rest looks the same as usual.

Local Heat will read that secret, parse the credential information out,
replace current authentication plugin in context, and make remote calls.

Heat will not store your credential information anywhere. so your secret
security will remains within Barbican. That means if you wish to change your
credential or make sure other people can't access to it. All you need to do is
to update your Barbican secret or strong the security for it.
But aware of this. If you plan to switch the credential content, make sure that
won't affect resources/stacks in remote site. So do such actions with super
care.


Use CA cert (Optional)
----------------------

For production clouds, it's very important to have SSL support. Here we
provide CA cert method for your SSL access. If you wish to use that, use
`ca_cert` under `context` property. Which `ca_cert` is the contents of a CA
Certificate file that can be used to verify a remote cloud or region's server
certificate.
Or you can use `insecure` (a boolean option) under `context` property if you
like to use insecure mode (For security concerns, don't do it!) and you don't
want to use CA cert.

Here is an example for you:

.. code-block:: yaml

  heat_template_version: rocky

  resources:
    stack_in_remote_cloud:
      type: OS::Heat::Stack
      properties:
        context:
          credential_secret_id: {$Your_Secret_ID}
          ca_cert: {$Contents of a CA cert}
        template: { get_file: "remote-app.yaml" }

.. note:: If insecure flag is on, ca_cert will be ignored.
