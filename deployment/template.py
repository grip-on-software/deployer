"""
HTML formatting utilities.
"""

from html import escape
import string
from requests.utils import quote

class Template(string.Formatter):
    """
    Formatter object which supports HTML encoding using the 'h' conversion
    type and URL encoding using the 'u' conversion type.
    """

    def convert_field(self, value, conversion):
        if conversion == 'h':
            return escape(value)
        if conversion == 'u':
            return quote(value)

        return super(Template, self).convert_field(value, conversion)
