from pyflakes.scripts import pyflakes
from pyflakes.checker import Checker


def report_with_bypass(self, messageClass, *args, **kwargs):
    message = messageClass(self.filename, *args, **kwargs)
    with open(self.filename, 'r') as code:
        if 'pyflakes_bypass' in code.readlines()[message.lineno - 1]:
            return
    self.messages.append(message)

# monkey patch checker to support bypass
Checker.report = report_with_bypass

pyflakes.main()
