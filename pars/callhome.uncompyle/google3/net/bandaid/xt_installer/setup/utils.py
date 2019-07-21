# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/utils.py
# Compiled at: 2019-01-31 05:23:32
"""Utility functions for XT Installer setup."""
import logging
import os
import subprocess
import time
import ipaddr

class Logger(object):
    """Handle application logging."""
    _log_file_name = None
    _log_file_path = None
    _log_handler = None

    def __init__(self, log_dir='/tmp', log_name='g2c_install', log_level=logging.DEBUG):
        """Sets up the logger.
        
        All log messages are written to a file /log_dir/log_name-YYYYMMDD-HHMMSS.log
        
        Args:
          log_dir: Directory where to put log file.
          log_name: Base name of the log file.
          log_level: Threshold of the logging messages.
        """
        self._log_file_name = '%s-%s.log' % (
         log_name, time.strftime('%Y%m%d-%H%M%S', time.localtime()))
        self._log_file_path = os.path.join(log_dir, self._log_file_name)
        formatter = logging.Formatter(fmt='%(levelname).1s %(asctime)s.%(msecs)06d %(process)7d %(filename)s:%(lineno)d] %(message)s', datefmt='%02m%02d %02H:%02M:%02S')
        file_handler = logging.FileHandler(self._log_file_path)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        self._log_handler = file_handler
        logger = logging.getLogger()
        logger.addHandler(file_handler)
        logger.setLevel(log_level)

    def ReadLogs(self):
        """Read the current content of the log file.
        
        Returns:
           The current content of log file or None if we couldn't access it.
        """
        self._log_handler.flush()
        try:
            with open(self._log_file_path, 'r') as logfile:
                logdata = logfile.read()
        except IOError:
            logging.error('Cannot read log file %s.', self._log_file_path)
            return

        return logdata

    def CopyLogs(self, destination_dir):
        """Copy log file to another directory.
        
        Args:
          destination_dir: Where to copy logfile.
        """
        if not destination_dir:
            return
        log_filename = os.path.join(destination_dir, self._log_file_name)
        logging.info("Copying log files to '%s'.", log_filename)
        logs = self.ReadLogs()
        if not logs:
            logging.error("Can't access logs!")
            return
        try:
            with open(os.path.join(log_filename), 'w') as logfile:
                logfile.write(logs)
        except IOError:
            logging.error("Can't copy logs!")


def RunCommand(command, dry_run=False, input_buffer=None):
    """Run command in shell.
    
    Wrapper for running external commands in shell that logs all output and
    returns it with exit status.
    
    Args:
      command: A string with command to run.
      dry_run: Do not actually run the command, only log it (bool).
      input_buffer: A string to send to stdin of the command.
    
    Returns:
      (stdout, stderr, code): A tuple containning command's output and exit code.
    """
    if dry_run:
        logging.info('Skipping command %s', command)
        return ('', '', 0)
    logging.info('Running command %s', command)
    start_time = time.time()
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        try:
            out, err = process.communicate(input_buffer)
        finally:
            returncode = process.wait()

    except OSError as e:
        out = ''
        err = e.child_traceback if hasattr(e, 'child_traceback') else str(e)
        returncode = 255

    end_time = time.time()
    loglevel = logging.INFO
    status = 'successful'
    if returncode != 0:
        loglevel = logging.ERROR
        status = 'failed'
    logmsg = 'Command %s: "%s" (time: %d, return: %d)\nstdout:\n%s\nstderr:\n%s' % (
     status, command, end_time - start_time, returncode, out, err)
    logging.log(loglevel, logmsg)
    return (
     out, err, returncode)


def ParseProcCmdline(proc_cmdline):
    """Parse /proc/cmdline into a dict of key,value pairs.
    
    Args:
      proc_cmdline: path to kernel command line file.
    
    Returns:
      A dict of key,value pairs. Arguments in /proc/cmdline that aren't of the
      form key=value will have a value of True.
    """
    params = {}
    cmdline = ''
    with open(proc_cmdline, 'r') as f:
        cmdline = f.read().strip()
    args = cmdline.split()
    for arg in args:
        if '=' in arg:
            key, val = arg.split('=', 1)
        else:
            key = arg
            val = True
        params[key] = val

    return params


def Print(msg, quiet=False):
    """Print the msg (str) if quiet is False."""
    if not quiet:
        print msg


def PromptUserForContinuation(prompt, debug_mode=False):
    """Interactively present a message to the user.
    
    Arguments:
      prompt: string to present the user.
      debug_mode: allow breaking out of prompt with Ctrl-C (terminates program).
    """
    msg = '%s [Press Enter to continue]' % prompt
    while True:
        try:
            raw_input(msg).strip()
        except KeyboardInterrupt:
            if debug_mode:
                raise KeyboardInterrupt('Break from: "%s"' % msg)
            print
        except EOFError:
            print '^D'
        except:
            print
        else:
            if debug_mode:
                logging.debug('PROMPT: %s', msg)
            return


def PromptUserForBool(prompt, default, quiet, debug_mode=False):
    """Interactively ask the user a yes or no question.
    
    Arguments:
      prompt: string to present the user.
      default: default value if the user just hits ENTER.
      quiet: do not print detailed messages.
      debug_mode: allow breaking out of prompt with Ctrl-C (terminates program).
    
    Returns:
      Boolean value corresponding to the user's answer.
    """
    default_answer = 'Y' if default else 'N'
    result = None
    msg = '%s [%s]: ' % (prompt, default_answer)
    while result is None:
        try:
            answer = raw_input(msg).strip()
        except KeyboardInterrupt:
            if debug_mode:
                raise KeyboardInterrupt('Break from: "%s"' % msg)
            print
        except EOFError:
            print '^D'
        except:
            print
        else:
            if not answer:
                result = default
            elif answer[0] in 'Yy':
                result = True
            elif answer[0] in 'Nn':
                result = False
            elif not quiet:
                print
                print "Please enter 'Y' or 'N'."
                print

    if debug_mode:
        logging.debug('PROMPT: %s%s', msg, answer)
    return result


def PromptUserForInt(prompt, min_value, max_value, default, quiet, debug_mode=False):
    """Interactively ask the user one from several options.
    
    Arguments:
      prompt: string to present the user.
      min_value: minimal number accepted
      max_value: maximal number accepted
      default: default value if the user just hits ENTER.
      quiet: do not print detailed messages.
      debug_mode: allow breaking out of prompt with Ctrl-C (terminates program).
    
    Returns:
      Number in [min_value, max_value] range
    """
    default_answer = default if default is not None else ''
    result = None
    msg = '%s [%s]: ' % (prompt, default_answer)
    while result is None:
        try:
            answer = raw_input(msg).strip()
        except KeyboardInterrupt:
            if debug_mode:
                raise KeyboardInterrupt('Break from: "%s"' % msg)
            print
        except EOFError:
            print '^D'
        except:
            print
        else:
            if not answer:
                answer = default_answer
            try:
                answer = int(answer)
                if max_value >= answer >= min_value:
                    result = answer
                else:
                    raise ValueError
            except ValueError:
                if not quiet:
                    print
                    print 'Invalid input, please enter a number between %d and %d.' % (
                     min_value, max_value)
                    print

    if debug_mode:
        logging.debug('PROMPT: %s%s', msg, answer)
    return result


def PromptUserForIPAddress(prompt, default, quiet, debug_mode=False):
    """Interactively ask the user an IP address.
    
    Arguments:
      prompt: string to present the user.
      default: default string value if the user just hits ENTER.
      quiet: do not print detailed messages.
      debug_mode: allow breaking out of prompt with Ctrl-C (terminates program).
    
    Returns:
      A valid ipaddr.IPAddress based on the user's input.
    """
    default_answer = default if default is not None else ''
    msg = '%s [%s]: ' % (prompt, default_answer)
    result = None
    while result is None:
        try:
            answer = raw_input(msg).strip()
        except KeyboardInterrupt:
            if debug_mode:
                raise KeyboardInterrupt('Break from: "%s"' % msg)
            print
        except EOFError:
            print '^D'
        except:
            print
        else:
            if not answer:
                answer = default_answer
            try:
                result = ipaddr.IPAddress(answer)
            except ValueError:
                if not quiet:
                    print
                    print 'Invalid format.'
                    print

    if debug_mode:
        logging.debug('PROMPT: %s%s', msg, answer)
    return result


def PromptUserForIPNetwork(prompt, default, quiet, debug_mode=False):
    """Interactively ask the user an IP subnet in CIDR notation.
    
    Arguments:
      prompt: string to present the user.
      default: default string value if the user just hits ENTER.
      quiet: do not print detailed messages.
      debug_mode: allow breaking out of prompt with Ctrl-C (terminates program).
    
    Returns:
      A valid ipaddr.IPNetwork based on the user's input.
    """
    default_answer = default if default is not None else ''
    msg = '%s [%s]: ' % (prompt, default_answer)
    result = None
    while result is None:
        try:
            answer = raw_input(msg).strip()
        except KeyboardInterrupt:
            if debug_mode:
                raise KeyboardInterrupt('Break from: "%s"' % msg)
            print
        except EOFError:
            print '^D'
        except:
            print
        else:
            if not answer:
                answer = default_answer
            try:
                if '/' not in str(answer):
                    raise ValueError
                result = ipaddr.IPNetwork(answer)
            except ValueError:
                if not quiet:
                    print
                    print 'Invalid format.'
                    print

    if debug_mode:
        logging.debug('PROMPT: %s%s', msg, answer)
    return result


def PromptUserForChoice(prompt, choices, default, quiet, debug_mode=False):
    """Interactively ask the user one from several options.
    
    Arguments:
      prompt: string to present the user.
      choices: list of possible inputs
      default: default value if the user just hits ENTER.
      quiet: do not print detailed messages.
      debug_mode: allow breaking out of prompt with Ctrl-C (terminates program).
    
    Returns:
      Chosen item from the choices list
    """
    default_answer = default or ''
    msg = '%s [%s]: ' % (prompt, default_answer)
    result = None
    while result is None:
        try:
            answer = raw_input(msg).strip()
        except KeyboardInterrupt:
            if debug_mode:
                raise KeyboardInterrupt('Break from: "%s"' % msg)
            print
        except EOFError:
            print '^D'
        except:
            print
        else:
            if not answer:
                answer = default_answer
            if answer in choices:
                result = answer
            elif not quiet:
                choices_as_str = ', '.join(('"%s"' % item for item in choices))
                print
                print 'Invalid input, please enter one of: %s.' % choices_as_str
                print

    if debug_mode:
        logging.debug('PROMPT: %s%s', msg, answer)
    return result
# okay decompiling ./google3/net/bandaid/xt_installer/setup/utils.pyc
