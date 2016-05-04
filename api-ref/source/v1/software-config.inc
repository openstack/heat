.. -*- rst -*-

======================
Software configuration
======================




List deployments
================

.. rest_method::  GET /v1/{tenant_id}/software_deployments

Lists all available software deployments.


Normal response codes: 200
Error response codes:404,500,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - server_id: server_id
   - config_id: config_id
   - output_values: output_values
   - creation_time: creation_time
   - updated_at: updated_at
   - input_values: input_values
   - action: action
   - status_reason: status_reason
   - id: id



Response Example
----------------

.. literalinclude:: samples/deployments-list-response.json
   :language: javascript








Create deployment
=================

.. rest_method::  POST /v1/{tenant_id}/software_deployments

Creates a software deployment.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - status: status
   - server_id: server_id
   - config_id: config_id
   - stack_user_project_id: stack_user_project_id
   - action: action
   - status_reason: status_reason
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: samples/deployment-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - server_id: server_id
   - config_id: config_id
   - output_values: output_values
   - creation_time: creation_time
   - updated_at: updated_at
   - input_values: input_values
   - action: action
   - status_reason: status_reason
   - id: id



Response Example
----------------

.. literalinclude:: samples/deployment-create-response.json
   :language: javascript




Show server configuration metadata
==================================

.. rest_method::  GET /v1/{tenant_id}/software_deployments/metadata/{server_id}

Shows the deployment configuration metadata for a server.

Use the ``group`` property to specify the configuration hook to
which the pass the metadata item.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - server_id: server_id
   - tenant_id: tenant_id




Response Example
----------------

.. literalinclude:: samples/deployment-metadata-response.json
   :language: javascript




Create configuration
====================

.. rest_method::  POST /v1/{tenant_id}/software_configs

Creates a software configuration.


Normal response codes: 200
Error response codes:404,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - inputs: inputs
   - group: group
   - name: name
   - outputs: outputs
   - config: config
   - options: options
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: samples/config-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - inputs: inputs
   - group: group
   - name: name
   - outputs: outputs
   - creation_time: creation_time
   - config: config
   - options: options



Response Example
----------------

.. literalinclude:: samples/config-create-response.json
   :language: javascript







Show deployment details
=======================

.. rest_method::  GET /v1/{tenant_id}/software_deployments/{deployment_id}

Shows details for a software deployment.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - deployment_id: deployment_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - server_id: server_id
   - config_id: config_id
   - output_values: output_values
   - creation_time: creation_time
   - updated_at: updated_at
   - input_values: input_values
   - action: action
   - status_reason: status_reason
   - id: id



Response Example
----------------

.. literalinclude:: samples/deployment-show-response.json
   :language: javascript




Update deployment
=================

.. rest_method::  PUT /v1/{tenant_id}/software_deployments/{deployment_id}

Updates a software deployment.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - action: action
   - output_values: output_values
   - config_id: config_id
   - status: status
   - status_reason: status_reason
   - tenant_id: tenant_id
   - deployment_id: deployment_id

Request Example
---------------

.. literalinclude:: samples/deployment-update-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - server_id: server_id
   - config_id: config_id
   - output_values: output_values
   - creation_time: creation_time
   - updated_at: updated_at
   - input_values: input_values
   - action: action
   - status_reason: status_reason
   - id: id



Response Example
----------------

.. literalinclude:: samples/deployment-update-response.json
   :language: javascript




Delete deployment
=================

.. rest_method::  DELETE /v1/{tenant_id}/software_deployments/{deployment_id}

Deletes a software deployment.

Error response codes:204,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - deployment_id: deployment_id






Show configuration details
==========================

.. rest_method::  GET /v1/{tenant_id}/software_configs/{config_id}

Shows details for a software configuration.


Normal response codes: 200
Error response codes:404,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - config_id: config_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - inputs: inputs
   - group: group
   - name: name
   - outputs: outputs
   - creation_time: creation_time
   - config: config
   - options: options



Response Example
----------------

.. literalinclude:: samples/config-show-response.json
   :language: javascript







Delete config
=============

.. rest_method::  DELETE /v1/{tenant_id}/software_configs/{config_id}

Deletes a software configuration.

Error response codes:204,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - config_id: config_id





