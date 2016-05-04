.. -*- rst -*-

===============
Stack resources
===============




Show resource metadata
======================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}/metadata

Shows metadata for a resource.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - resource_name: resource_name
   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id




Response Example
----------------

.. literalinclude:: samples/resource-metadata-response.json
   :language: javascript




Show resource data
==================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}

Shows data for a resource.


Normal response codes: 200
Error response codes:404,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - resource_name: resource_name
   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - resource_name: resource_name
   - resource: resource
   - description: description
   - logical_resource_id: logical_resource_id
   - creation_time: creation_time
   - resource_status: resource_status
   - updated_time: updated_time
   - required_by: required_by
   - resource_status_reason: resource_status_reason
   - physical_resource_id: physical_resource_id
   - resource_type: resource_type



Response Example
----------------

.. literalinclude:: samples/resource-show-response.json
   :language: javascript







List resources
==============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources

Lists resources in a stack.


Normal response codes: 200
Error response codes:404,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id
   - nested_depth: nested_depth
   - with_detail: with_detail


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - resource_name: resource_name
   - description: description
   - logical_resource_id: logical_resource_id
   - creation_time: creation_time
   - resource_status: resource_status
   - updated_time: updated_time
   - required_by: required_by
   - resources: resources
   - resource_status_reason: resource_status_reason
   - physical_resource_id: physical_resource_id
   - resource_type: resource_type



Response Example
----------------

.. literalinclude:: samples/resources-list-response.json
   :language: javascript







Send a signal to a resource
===========================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}/signal

Sends a signal to a resource.

The contents of the request body depends on the resource to which
you send a signal.

Some resources cannot receive signals. If you send them a signal,
they return a 400 error code.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - resource_name: resource_name
   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id




Response Example
----------------

.. literalinclude:: 
   :language: javascript



