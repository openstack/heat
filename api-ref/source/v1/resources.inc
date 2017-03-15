.. -*- rst -*-

===============
Stack resources
===============


Find stack resources
====================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_identity}/resources

Finds the canonical URL for a resource list of a stack.

The canonical URL is returned for only non-deleted stacks. To fetch
the resource list for deleted stacks, use the following endpoint:

::

   /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 302

.. rest_status_code:: error status.yaml

   - 401
   - 404

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_identity: stack_identity

Response Parameter
------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - location: location

Response Example
----------------

.. literalinclude:: samples/stack-find-response.json
   :language: javascript


List stack resources
====================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources

Lists resources in a stack based on filtering parameters like resource
name, status, type, action, id and physical_resource_id. These parameters could
be used multiple times.

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
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - type: resource_type_query
   - status: resource_status_query
   - name: resource_name_query
   - action: resource_action_query
   - id: resource_id_query
   - physical_resource_id: physical_resource_id_query
   - nested_depth: nested_depth
   - with_detail: with_detail

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - resources: resources_list
   - creation_time: creation_time
   - links: links
   - logical_resource_id: logical_resource_id
   - physical_resource_id: physical_resource_id
   - required_by: required_by
   - resource_name: resource_name
   - resource_status: resource_status
   - resource_status_reason: resource_status_reason
   - resource_type: resource_type
   - updated_time: updated_time

Response Example
----------------

.. literalinclude:: samples/resources-list-response.json
   :language: javascript


Show resource data
==================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}

Shows data for a resource.

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
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - resource_name: resource_name_url
   - with_attr: with_attr

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - resource: resource
   - attributes: attributes
   - creation_time: creation_time
   - description: description
   - links: resource_links
   - logical_resource_id: logical_resource_id
   - physical_resource_id: physical_resource_id
   - required_by: required_by
   - resource_name: resource_name
   - resource_status: resource_status
   - resource_status_reason: resource_status_reason
   - resource_type: resource_type
   - updated_time: updated_time

Response Example
----------------

.. literalinclude:: samples/resource-show-response.json
   :language: javascript


Show resource metadata
======================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}/metadata

Shows metadata for a resource.

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
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - resource_name: resource_name_url

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - metadata: metadata

Response Example
----------------

.. literalinclude:: samples/resource-metadata-response.json
   :language: javascript


Send a signal to a resource
===========================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}/signal

Sends a signal to a resource.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400: resource_signal
   - 401
   - 404

Request Parameters
------------------

The contents of the request body depends on the resource to which you send a
signal.

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - resource_name: resource_name_url

Response Example
----------------

This operation does not return a response body.


Mark a resource as unhealthy
============================

.. rest_method::  PATCH /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name_or_physical_id}

Mark the specified resource in the stack as unhealthy.

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
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - resource_name_or_physical_id: resource_name_or_physical_id_url
   - mark_unhealthy: mark_unhealthy
   - resource_status_reason: resource_update_status_reason

Response Example
----------------

This operation does not return a response body.
