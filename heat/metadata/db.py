DB = {}


class ConflictError(Exception):
    pass

class StackNotFoundError(Exception):
    pass

class ResourceNotFoundError(Exception):
    pass


def list_stacks():
    return DB.keys()

def create_stack(name, stack):
    global DB
    if name in DB:
        raise ConflictError(name)
    data = {}
    # TODO(shadower): validate the stack input format
    data['name'] = name
    data['heat_id'] = stack['id']
    data['resources'] = {}
    DB[name] = data
    return data

def list_resources(stack_name):
    if not stack_name in DB:
        raise StackNotFoundError(stack_name)
    stack = DB[stack_name]
    try:
        resources = stack['resources'].keys()
    except:
        resources = []
    return resources

def get_resource(stack_name, resource_id):
    if not stack_name in DB:
        raise StackNotFoundError(stack_name)
    stack = DB[stack_name]

    if not resource_id in stack['resources']:
        raise ResourceNotFoundError(resource_id)
    return stack['resources'][resource_id]

def create_resource_metadata(stack_name, resource_id, metadata):
    if not stack_name in DB:
        raise StackNotFoundError(stack_name)
    stack = DB[stack_name]

    if resource_id in stack['resources']:
        raise ConflictError(resource_id)
    stack['resources'][resource_id] = metadata

def update_resource_metadata(stack_name, resource_id, metadata):
    if not stack_name in DB:
        raise StackNotFoundError(stack_name)
    stack = DB[stack_name]

    if not resource_id in stack['resources']:
        raise ResourceNotFoundError(resource_id)
    stack['resources'][resource_id] = metadata
