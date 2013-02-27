from pyflakes.scripts import pyflakes
from pyflakes.checker import Checker


def report_with_bypass(self, messageClass, *args, **kwargs):
    text_lineno = args[0] - 1
    with open(self.filename, 'r') as code:
        if code.readlines()[text_lineno].find('pyflakes_bypass') >= 0:
            return
    self.messages.append(messageClass(self.filename, *args, **kwargs))

# monkey patch checker to support bypass
Checker.report = report_with_bypass

pyflakes.main()
