"""Console Status Display Tool command runner library."""

import errno
import logging
import os
import shlex
import signal
import subprocess
import tempfile
import threading
import time


class Error(Exception):
  pass


class Timeout(Error):
  pass


# Constants denoting output capture.
STDOUT = 'STDOUT'
STDERR = 'STDERR'
STDOUT_STDERR = 'STDOUT_STDERR'

# Default command timeout.
DEFAULT_COMMAND_TIMEOUT = 60


class CommandRunner(object):
  """Run commands directly in the local environment via subprocess."""

  class Result(object):
    """The result of a command execution.

    Attributes:
      exit_code: The exit code of the child process (int).
      output: Captured output of the child process, if any (string).
    """

    def __init__(self, exit_code, output=None):
      self.exit_code = exit_code
      self.output = output

  def _KillProcess(self, process, kill_timeout=3):
    """Gracefully kill a given process and all its children.

    Args:
      process: Process group leader to kill (subprocess.Popen).
      kill_timeout: Seconds to wait before sending SIGKILL signal (int).
    """
    try:
      logging.debug('Sending SIGTERM to PID %d.', process.pid)
      os.killpg(process.pid, signal.SIGTERM)
      logging.debug('Waiting %d seconds before sending SIGKILL to PID %d.',
                    kill_timeout, process.pid)
      time.sleep(kill_timeout)
      logging.debug('Sending SIGKILL to PID %d.', process.pid)
      os.killpg(process.pid, signal.SIGKILL)
    except OSError as error:
      if error.errno == errno.ESRCH:
        logging.debug('Process terminated before we tried to kill it.')
      else:
        raise  # Unexpected error while killing process.

  def Run(
      self, command, timeout=None, capture_output=STDOUT_STDERR, stdin=None,
      stdout=None, stderr=None):
    """Run a command locally.

    Args:
      command: The command to run (string).
      timeout: Maximum time the command is allowed to take (float, seconds).
      capture_output: What output to capture. Must be one of:
          - STDOUT: Return standard output
          - STDERR: Return standard error
          - STDOUT_STDERR: Redirect stderr to stdout and return stdout
      stdin: Opened file descriptor. If supplied, capture_output is ignored.
      stdout: Opened file descriptor. If supplied, capture_output is ignored.
      stderr: Opened file descriptor. If supplied, capture_output is ignored.

    Returns:
      Result of the command executed (CommandRunner.Result).

    Raises:
      Timeout: If process takes longer than 'timeout' to run.
      ValueError: If invalid value specified for capture_output.
    """
    if timeout is None:
      timeout = DEFAULT_COMMAND_TIMEOUT

    def ConfigureSubprocess():
      # Create a new session and process group and make this subprocess the
      # new group and session leader, disconnecting any controlling terminal.
      # This allows us to signal the subprocess and all its children on timeout.
      os.setsid()

    popen_kwargs = {
        'args': shlex.split(command),
        'preexec_fn': ConfigureSubprocess,
    }
    with tempfile.TemporaryFile() as output_file:
      with open(os.devnull, 'r+') as dev_null:
        if stdin or stdout or stderr:
          popen_kwargs['stdin'] = stdin
          popen_kwargs['stdout'] = stdout
          popen_kwargs['stderr'] = stderr
        else:
          if capture_output == STDOUT:
            popen_kwargs['stdin'] = dev_null
            popen_kwargs['stdout'] = output_file
            popen_kwargs['stderr'] = dev_null
          elif capture_output == STDERR:
            popen_kwargs['stdin'] = dev_null
            popen_kwargs['stdout'] = dev_null
            popen_kwargs['stderr'] = output_file
          elif capture_output == STDOUT_STDERR:
            popen_kwargs['stdin'] = dev_null
            popen_kwargs['stdout'] = output_file
            popen_kwargs['stderr'] = subprocess.STDOUT
          else:
            raise ValueError('Unsupported capture_output: %r' % capture_output)

        logging.debug('Running: %s', command)
        process = subprocess.Popen(**popen_kwargs)

        process_thread = threading.Thread(target=process.communicate)
        process_thread.start()
        process_thread.join(timeout)

        if process_thread.is_alive():
          self._KillProcess(process=process)
          raise Timeout()

        output_file.seek(0)
        output = output_file.read()

        return CommandRunner.Result(exit_code=process.returncode, output=output)
