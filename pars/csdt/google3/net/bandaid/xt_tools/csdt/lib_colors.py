"""Console Status Display Tool color handling library."""

import collections
import re


COLOR_MODE_OFF = 0
COLOR_MODE_DEBUG = 1
COLOR_MODE_ANSI = 2

RE_TOKENS_OFF = re.compile(r'({c\.[a-z]+})')
RE_TOKENS_DEBUG = re.compile(r'(<[\*RGYBMCW0]>)')
RE_TOKENS_ANSI = re.compile(r'(\x1b\[\d*m\x0f?)')


ColorCodes = collections.namedtuple(
    'ColorCodes',
    'bold red green yellow blue magenta cyan white reset')


def GetColorCodes(color_mode=COLOR_MODE_ANSI):
  """Get color codes.

  Args:
    color_mode: Color mode (int).

  Raises:
    ValueError: If unsupported color mode is requested.

  Returns:
    ColorCodes instance with named attributes for each color.
  """
  if color_mode == COLOR_MODE_OFF:
    return ColorCodes(
        bold='',
        red='',
        green='',
        yellow='',
        blue='',
        magenta='',
        cyan='',
        white='',
        reset='')

  if color_mode == COLOR_MODE_DEBUG:
    return ColorCodes(
        bold='<*>',
        red='<R>',
        green='<G>',
        yellow='<Y>',
        blue='<B>',
        magenta='<M>',
        cyan='<C>',
        white='<W>',
        reset='<0>')

  if color_mode == COLOR_MODE_ANSI:
    return ColorCodes(
        bold='\x1b[1m',
        red='\x1b[31m',
        green='\x1b[32m',
        yellow='\x1b[33m',
        blue='\x1b[34m',
        magenta='\x1b[35m',
        cyan='\x1b[36m',
        white='\x1b[37m',
        reset='\x1b[m\x0f')

  raise ValueError('Unsupported color mode: %r' % color_mode)


def GetStringTokens(string, color_mode=COLOR_MODE_ANSI):
  """Get a list of string tokens.

  Args:
    string: String to split into tokens (str).
    color_mode: Color mode (one of COLOR_MODE_*).

  Raises:
    ValueError: If unsupported color mode is requested.

  Returns:
    List of string tokens (list).
  """
  if color_mode == COLOR_MODE_OFF:
    return [token for token in RE_TOKENS_OFF.split(string) if token]

  if color_mode == COLOR_MODE_DEBUG:
    return [token for token in RE_TOKENS_DEBUG.split(string) if token]

  if color_mode == COLOR_MODE_ANSI:
    return [token for token in RE_TOKENS_ANSI.split(string) if token]

  raise ValueError('Unsupported color mode: %r' % color_mode)
