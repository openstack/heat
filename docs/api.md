Heat OpenStack API Reference
============================

List Stacks
-----------

```
GET /v1/{tenant_id}/stacks
```

Parameters:

* `tenant_id` The unique identifier of the tenant or account

Create Stack
------------

```
POST /v1/{tenant_id}/stacks

{
    "stack_name": "{stack_name}",
    "template_url": "{template_url}",
    "parameters": {
        "{key1}": "{value1}",
        "{key2}": "{value2}"
    },
    "timeout_mins": {timeout_mins}
}
```

Parameters:

* `tenant_id` The unique identifier of the tenant or account
* `stack_name` The name of the stack to create
* `template_url` The URL of the template to instantiate
* `template` A JSON template to instantiate - this takes precendence over the `template_url` if both are supplied
* `keyn`, `valuen` User-defined parameters to pass to the Template
* `timeout_mins` The timeout for stack creation in minutes

Result:

```
HTTP/1.1 201 Created
Location: http://heat.example.com:8004/v1/{tenant_id}/stacks/{stack_name}/{stack_id}
```

Find Stack ID
-------------

```
GET /v1/{tenant_id}/stacks/{stack_name}
```

Parameters:

* `stack_name` The name of the stack to look up

Result:

```
HTTP/1.1 302 Found
Location: http://heat.example.com:8004/v1/{tenant_id}/stacks/{stack_name}/{stack_id}
```

This operation also works with verbs other than `GET`, so you can also use it to perform `PUT` and `DELETE` operations on a current stack. Just set your client to follow redirects. Note that when redirecting, the request method should **not** change, as defined in [RFC2626](http://www.w3.org/Protocols/rfc2616/rfc2616-sec10.html#sec10.3.3). However, in many clients the default behaviour is to change the method to `GET` when receiving a 302 because this behaviour is ubiquitous in web browsers.

Get Stack Data
--------------

```
GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}
```

Parameters:

* `stack_name` The name of the stack to look up
* `stack_id` The unique identifier of the stack to look up

Retrieve Stack Template
-----------------------

```
GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/template
```

Parameters:

* `tenant_id` The unique identifier of the tenant or account
* `stack_name` The name of the stack to look up
* `stack_id` The unique identifier of the stack to look up

Update Stack
------------

```
PUT /v1/{tenant_id}/stacks/{stack_name}/{stack_id}

{
    "template_url": "{template_url}",
    "parameters": {
        "{key1}": "{value1}",
        "{key2}": "{value2}"
    },
    "timeout_mins": {timeout_mins}
}
```

Parameters:

* `tenant_id` The unique identifier of the tenant or account
* `stack_name` The name of the stack to create
* `stack_id` The unique identifier of the stack to look up
* `template_url` The URL of the updated template
* `template` An updated JSON template - this takes precendence over the `template_url` if both are supplied
* `keyn`, `valuen` User-defined parameters to pass to the Template
* `timeout_mins` The timeout for stack creation in minutes

Result:

```
HTTP/1.1 202 Accepted
```

Delete Stack
------------

```
DELETE /v1/{tenant_id}/stacks/{stack_name}/{stack_id}
```

Parameters:

* `tenant_id` The unique identifier of the tenant or account
* `stack_name` The name of the stack to create
* `stack_id` The unique identifier of the stack to look up

Result:

```
HTTP/1.1 204 No Content
```

Validate Template
-----------------

```
POST /v1/{tenant_id}/validate

{
    "template_url": "{template_url}",
    "parameters": {
        "{key1}": "{value1}",
        "{key2}": "{value2}"
    }
}
```

Parameters:

* `tenant_id` The unique identifier of the tenant or account
* `template_url` The URL of the template to validate
* `template` A JSON template to validate - this takes precendence over the `template_url` if both are supplied.
* `keyn`, `valuen` User-defined parameters to pass to the Template

List Stack Resources
--------------------

```
GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources
```

Parameters:

* `tenant_id` The unique identifier of the tenant or account
* `stack_name` The name of the stack to look up
* `stack_id` The unique identifier of the stack to look up

Get Resource
------------

```
GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}
```

Parameters:

* `tenant_id` The unique identifier of the tenant or account
* `stack_name` The name of the stack to look up
* `stack_id` The unique identifier of the stack to look up
* `resource_name` The name of the resource in the template

Get Resource Metadata
---------------------

```
GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}/metadata
```

Parameters:

* `tenant_id` The unique identifier of the tenant or account
* `stack_name` The name of the stack to look up
* `stack_id` The unique identifier of the stack to look up
* `resource_name` The name of the resource in the template
