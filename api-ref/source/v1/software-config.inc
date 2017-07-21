.. -*- rst -*-

======================
Software configuration
======================

Create configuration
====================

.. rest_method::  POST /v1/{tenant_id}/software_configs

Creates a software configuration.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - inputs: inputs
   - group: group
   - name: config_name
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

   - id: config_id
   - inputs: inputs
   - group: group
   - name: config_name
   - outputs: outputs
   - creation_time: creation_time
   - updated_time: updated_time
   - config: config
   - options: options
   - software_config: software_config

Response Example
----------------

.. literalinclude:: samples/config-create-response.json
   :language: javascript


List configs
============

.. rest_method::  GET /v1/{tenant_id}/software_configs

Lists all available software configurations.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - limit: limit
   - marker: marker

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - creation_time: creation_time
   - group: group
   - id: config_id
   - name: config_name
   - software_configs: software_configs

Response Example
----------------

.. literalinclude:: samples/configs-list-response.json
   :language: javascript


Show configuration details
==========================

.. rest_method::  GET /v1/{tenant_id}/software_configs/{config_id}

Shows details for a software configuration.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - config_id: config_id_url


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - config: config
   - creation_time: creation_time
   - group: group
   - id: config_id
   - inputs: inputs
   - name: config_name
   - options: options
   - outputs: outputs
   - software_config: software_config


Response Example
----------------

.. literalinclude:: samples/config-show-response.json
   :language: javascript


Delete config
=============

.. rest_method::  DELETE /v1/{tenant_id}/software_configs/{config_id}

Deletes a software configuration.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 204

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - config_id: config_id_url


Create deployment
=================

.. rest_method::  POST /v1/{tenant_id}/software_deployments

Creates a software deployment.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - action: deployment_action
   - config_id: deployment_config_id
   - input_values: input_values
   - server_id: server_id
   - stack_user_project_id: stack_user_project_id
   - status: deployment_status
   - status_reason: deployment_status_reason

Request Example
---------------

.. literalinclude:: samples/deployment-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - action: deployment_action
   - config_id: deployment_config_id
   - creation_time: creation_time
   - id: deployment_id
   - input_values: input_values
   - output_values: deployment_output_values
   - server_id: server_id
   - software_deployment: software_deployment
   - status: deployment_status
   - status_reason: deployment_status_reason
   - updated_time: deployment_updated_time

Response Example
----------------

.. literalinclude:: samples/deployment-create-response.json
   :language: javascript


List deployments
================

.. rest_method::  GET /v1/{tenant_id}/software_deployments

Lists all available software deployments.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - server_id: deployment_server_id_query

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - action: deployment_action
   - config_id: deployment_config_id
   - creation_time: creation_time
   - id: deployment_id
   - input_values: input_values
   - output_values: deployment_output_values
   - server_id: server_id
   - software_deployments: software_deployments
   - status: deployment_status
   - status_reason: deployment_status_reason
   - updated_time: deployment_updated_time

Response Example
----------------

.. literalinclude:: samples/deployments-list-response.json
   :language: javascript


Show deployment details
=======================

.. rest_method::  GET /v1/{tenant_id}/software_deployments/{deployment_id}

Shows details for a software deployment.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - deployment_id: deployment_id_url

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - action: deployment_action
   - config_id: deployment_config_id
   - creation_time: creation_time
   - id: deployment_id
   - input_values: input_values
   - output_values: deployment_output_values
   - server_id: server_id
   - software_deployment: software_deployment
   - status: deployment_status
   - status_reason: deployment_status_reason
   - updated_time: deployment_updated_time

Response Example
----------------

.. literalinclude:: samples/deployment-show-response.json
   :language: javascript


Update deployment
=================

.. rest_method::  PUT /v1/{tenant_id}/software_deployments/{deployment_id}

Updates a software deployment.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - deployment_id: deployment_id_url
   - action: deployment_action
   - config_id: deployment_config_id
   - input_values: input_values
   - output_values: deployment_output_values
   - status: deployment_status
   - status_reason: deployment_status_reason

Request Example
---------------

.. literalinclude:: samples/deployment-update-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - action: deployment_action
   - config_id: deployment_config_id
   - creation_time: creation_time
   - id: deployment_id
   - input_values: input_values
   - output_values: deployment_output_values
   - server_id: server_id
   - software_deployments: software_deployments
   - status: deployment_status
   - status_reason: deployment_status_reason
   - updated_time: deployment_updated_time

Response Example
----------------

.. literalinclude:: samples/deployment-update-response.json
   :language: javascript

Delete deployment
=================

.. rest_method::  DELETE /v1/{tenant_id}/software_deployments/{deployment_id}

Deletes a software deployment.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 204

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - deployment_id: deployment_id_url
   - tenant_id: tenant_id

Show server configuration metadata
==================================

.. rest_method::  GET /v1/{tenant_id}/software_deployments/metadata/{server_id}

Shows the deployment configuration metadata for a server.

Use the ``group`` property to specify the configuration hook to
which the pass the metadata item.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - server_id: deployment_server_id_url
   - tenant_id: tenant_id

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - config: config
   - creation_time: creation_time
   - group: group
   - id: config_id
   - inputs: inputs
   - metadata: deployment_metadata
   - name: config_name
   - options: options
   - outputs: outputs
   - updated_time: updated_time

Response Example
----------------

.. literalinclude:: samples/deployment-metadata-response.json
   :language: javascript
