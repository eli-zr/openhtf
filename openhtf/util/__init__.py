# Copyright 2014 Google Inc. All Rights Reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""One-off utilities."""

import logging
import re
import threading
import time
import typing
from typing import Any, Callable, Dict, Iterator, Optional, Text, Tuple, TypeVar
import weakref

import attr


def _log_every_n_to_logger(n: int, logger: Optional[logging.Logger], level: int,
                           message: Text, *args: Any) -> Callable[[], bool]:
  """Logs the given message every n calls to a logger.

  Args:
    n: Number of calls before logging.
    logger: The logger to which to log.
    level: The logging level (e.g. logging.INFO).
    message: A message to log
    *args: Any format args for the message.

  Returns:
    A method that logs and returns True every n calls.
  """
  logger = logger if logger else logging.getLogger()

  def _gen() -> Iterator[bool]:  # pylint: disable=missing-docstring
    while True:
      for _ in range(n):
        yield False
      logger.log(level, message, *args)
      yield True

  gen = _gen()
  return lambda: next(gen)


def log_every_n(n: int, level: int, message: Text,
                *args: Any) -> Callable[[], bool]:
  """Logs a message every n calls. See _log_every_n_to_logger."""
  return _log_every_n_to_logger(n, None, level, message, *args)


def time_millis() -> int:
  """The time in milliseconds."""
  return int(time.time() * 1000)


@attr.s(slots=True)
class NonLocalResult(object):
  """Holds a single result as a nonlocal variable.

  Comparable to using Python 3's nonlocal keyword, it allows an inner function
  to set the value in an outer function's namespace:

  def WrappingFunction():
    x = NonLocalResult()
    def InnerFunction():
      # This is what we'd do in Python 3:
      # nonlocal x
      # x = 1
      # In Python 2 we use NonLocalResult instead.
      x.result = 1
    InnerFunction()
    return x.result
  """

  result = attr.ib(type=Any, default=None)


# TODO(jethier): Add a pylint plugin to avoid the no-self-argument for this.
class classproperty(object):  # pylint: disable=invalid-name
  """Exactly what it sounds like.

  Note that classproperties don't have setters, so setting them will replace
  the classproperty with the new value. In most use cases (forcing subclasses
  to override the classproperty, for example) this is desired.
  """

  def __init__(self, func: Callable[..., Any]):
    self._func = func

  def __get__(self, instance, owner) -> Any:
    return self._func(owner)


def partial_format(target: Text, **kwargs: Any) -> Text:
  """Formats a string without requiring all values to be present.

  This function allows substitutions to be gradually made in several steps
  rather than all at once.  Similar to string.Template.safe_substitute.

  Args:
    target: format string.
    **kwargs: format replacements.

  Returns:
    Formatted string.
  """
  output = target[:]

  for tag, var in re.findall(r'(\{(.*?)\})', output):
    root = var.split('.')[0]  # dot notation
    root = root.split('[')[0]  # dict notation
    if root in kwargs:
      output = output.replace(tag, tag.format(**{root: kwargs[root]}))

  return output


FormatT = TypeVar('FormatT')


@typing.overload
def format_string(target: Text, kwargs: Dict[Text, Any]) -> Text:
  pass


@typing.overload
def format_string(target: Callable[..., Text], kwargs: Dict[Text, Any]) -> Text:
  pass


@typing.overload
def format_string(target: None, kwargs: Dict[Text, Any]) -> None:
  pass


@typing.overload
def format_string(target: FormatT, kwargs: Dict[Text, Any]) -> FormatT:
  pass


def format_string(target, kwargs):
  """Formats a string in any of three ways (or not at all).

  Args:
    target: The target string to format. This can be a function that takes a
      dict as its only argument, a string with {}- or %-based formatting, or a
      basic string with none of those. In the latter case, the string is
      returned as-is, but in all other cases the string is formatted (or the
      callback called) with the given kwargs. If this is None (or otherwise
      falsey), it is returned immediately.
    kwargs: The arguments to use for formatting. Passed to safe_format, %, or
      target if it's callable.

  Returns:
    Formatted string.
  """
  if target is None:
    return None
  if callable(target):
    return target(**kwargs)
  if not isinstance(target, str):
    return target
  if '{' in target:
    return partial_format(target, **kwargs)
  if '%' in target:
    return target % kwargs
  return target


class SubscribableStateMixin(object):
  """Gives an object the capability of notifying watchers of state changes.

  The state should be represented as a dictionary and returned by _asdict.
  An object that wants to watch this object's state should call
  asdict_with_event to get the current state and an event object. This object
  can then notify watchers holding those events that the state has changed by
  calling notify_update.
  """

  def __init__(self):
    super(SubscribableStateMixin, self).__init__()
    self._lock = threading.Lock()
    self._update_events = weakref.WeakSet()

  def _asdict(self) -> Dict[Text, Any]:
    raise NotImplementedError(
        'Subclasses of SubscribableStateMixin must implement _asdict.')

  def asdict_with_event(self) -> Tuple[Dict[Text, Any], threading.Event]:
    """Get a dict representation of this object and an update event.

    Returns:
      state: Dict representation of this object.
      update_event: An event that is guaranteed to be set if an update has been
          triggered since the returned dict was generated.
    """
    event = threading.Event()
    with self._lock:
      self._update_events.add(event)
    return self._asdict(), event

  def notify_update(self) -> None:
    """Notify any update events that there was an update."""
    with self._lock:
      for event in self._update_events:
        event.set()
      self._update_events.clear()
