# Copyright (c) 2009, Mario Vilas
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright notice,
#       this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice,this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the names of its
#       contributors may be used to endorse or promote products derived from
#       this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""
Breakpoints module.

@see: U{http://apps.sourceforge.net/trac/winappdbg/wiki/wiki/HowBreakpointsWork}

@group Breakpoints:
    Breakpoint, CodeBreakpoint, PageBreakpoint, HardwareBreakpoint,
    BufferWatch, Hook, ApiHook

@group Capabilities (private):
    BreakpointContainer
"""

__revision__ = "$Id$"

__all__ = [

    # Base class for breakpoints
    'Breakpoint',

    # Breakpoint implementations
    'CodeBreakpoint',
    'PageBreakpoint',
    'HardwareBreakpoint',

    # Hooks and watches
    'Hook',
    'ApiHook',
    'BufferWatch',

    # Breakpoint container capabilities
    'BreakpointContainer',

    ]

from system import Process, System, MemoryAddresses
from util import DebugRegister
from textio import HexDump
import win32

#==============================================================================

class Breakpoint (object):
    """
    Base class for breakpoints.
    Here's the breakpoints state machine.

    @see: L{CodeBreakpoint}, L{PageBreakpoint}, L{HardwareBreakpoint}

    @group Breakpoint states:
        DISABLED, ENABLED, ONESHOT, RUNNING
    @group State machine:
        hit, disable, enable, one_shot, running,
        is_disabled, is_enabled, is_one_shot, is_running,
        get_state, get_state_name
    @group Information:
        get_address, get_size, is_here
    @group Conditional breakpoints:
        is_conditional, is_unconditional,
        get_condition, set_condition, eval_condition
    @group Automatic breakpoints:
        is_automatic, is_interactive,
        get_action, set_action, run_action

    @cvar DISABLED: I{Disabled} S{->} Enabled, OneShot
    @cvar ENABLED:  I{Enabled}  S{->} I{Running}, Disabled
    @cvar ONESHOT:  I{OneShot}  S{->} I{Disabled}
    @cvar RUNNING:  I{Running}  S{->} I{Enabled}, Disabled

    @type DISABLED: int
    @type ENABLED:  int
    @type ONESHOT:  int
    @type RUNNING:  int

    @type stateNames: dict E{lb} int S{->} str E{rb}
    @cvar stateNames: User-friendly names for each breakpoint state.

    @type typeName: str
    @cvar typeName: User friendly breakpoint type string.
    """

    # I don't think transitions Enabled <-> OneShot should be allowed... plus
    #  it would require special handling to avoid setting the same bp twice

    DISABLED    = 0
    ENABLED     = 1
    ONESHOT     = 2
    RUNNING     = 3

    typeName    = 'breakpoint'

    stateNames  = {
        DISABLED    :   'disabled',
        ENABLED     :   'enabled',
        ONESHOT     :   'one shot',
        RUNNING     :   'running',
    }

    def __init__(self, address, size = 1, condition = True, action = None):
        """
        Breakpoint object.

        @type  address: int
        @param address: Memory address for breakpoint.

        @type  size: int
        @param size: Size of breakpoint in bytes (defaults to 1).

        @type  condition: function
        @param condition: (Optional) Condition callback function.

            The callback signature is::

                def condition_callback(event):
                    return True     # returns True or False

            Where B{event} is an L{Event} object,
            and the return value is a boolean
            (C{True} to dispatch the event, C{False} otherwise).

        @type  action: function
        @param action: (Optional) Action callback function.
            If specified, the event is handled by this callback instead of
            being dispatched normally.

            The callback signature is::

                def action_callback(event):
                    pass        # no return value

            Where B{event} is an L{Event} object.
        """
        self.__address   = address
        self.__size      = size
        self.__state     = self.DISABLED

        self.set_condition(condition)
        self.set_action(action)

    def __repr__(self):
        if self.is_disabled():
            state = 'Disabled'
        else:
            state = 'Active (%s)' % self.get_state_name()
        if self.get_condition() is True:
            condition = 'unconditional'
        else:
            condition = 'conditional'
        name = self.typeName
        size = self.get_size()
        if size == 1:
            address = HexDump.address( self.get_address() )
        else:
            begin   = self.get_address()
            end     = begin + size
            begin   = HexDump.address(begin)
            end     = HexDump.address(end)
            address = "range %s-%s" % (begin, end)
        msg = "<%s %s %s at remote address %s>"
        msg = msg % (state, condition, name, address)
        return msg

#------------------------------------------------------------------------------

    def is_disabled(self):
        """
        @rtype:  bool
        @return: C{True} if the breakpoint is in L{DISABLED} state.
        """
        return self.get_state() == self.DISABLED

    def is_enabled(self):
        """
        @rtype:  bool
        @return: C{True} if the breakpoint is in L{ENABLED} state.
        """
        return self.get_state() == self.ENABLED

    def is_one_shot(self):
        """
        @rtype:  bool
        @return: C{True} if the breakpoint is in L{ONESHOT} state.
        """
        return self.get_state() == self.ONESHOT

    def is_running(self):
        """
        @rtype:  bool
        @return: C{True} if the breakpoint is in L{RUNNING} state.
        """
        return self.get_state() == self.RUNNING

    def is_here(self, address):
        """
        @rtype:  bool
        @return: C{True} if the address is within the range of the breakpoint.
        """
        begin = self.get_address()
        end   = begin + self.get_size()
        return begin <= address < end

    def get_address(self):
        """
        @rtype:  int
        @return: The target memory address for the breakpoint.
        """
        return self.__address

    def get_size(self):
        """
        @rtype:  int
        @return: The size in bytes of the breakpoint.
        """
        return self.__size

    def get_span(self):
        """
        @rtype:  tuple( int, int )
        @return:
            Starting and ending address of the memory range
            covered by the breakpoint.
        """
        address = self.get_address()
        size    = self.get_size()
        return ( address, address + size )

    def get_state(self):
        """
        @rtype:  int
        @return: The current state of the breakpoint
            (L{DISABLED}, L{ENABLED}, L{ONESHOT}, L{RUNNING}).
        """
        return self.__state

    def get_state_name(self):
        """
        @rtype:  str
        @return: The name of the current state of the breakpoint.
        """
        return self.stateNames[ self.get_state() ]

#------------------------------------------------------------------------------

    def is_conditional(self):
        """
        @see: L{__init__}
        @rtype:  bool
        @return: C{True} if the breakpoint has a condition callback defined.
        """
        return self.__condition is not True

    def is_unconditional(self):
        """
        @rtype:  bool
        @return: C{True} if the breakpoint doesn't have a condition callback defined.
        """
        return self.__condition is True

    def get_condition(self):
        """
        @rtype:  bool, function
        @return: Returns the condition callback for conditional breakpoints.
            Returns C{True} for unconditional breakpoints.
        """
        return self.__condition

    def set_condition(self, condition = True):
        """
        Sets a new condition callback for the breakpoint.

        @see: L{__init__}

        @type  condition: function
        @param condition: (Optional) Condition callback function.
        """
        if condition in (False, None):
            condition = True
        self.__condition = condition

    def eval_condition(self, event):
        """
        Evaluates the breakpoint condition, if any was set.

        @type  event: L{Event}
        @param event: Debug event triggered by the breakpoint.

        @rtype:  bool
        @return: C{True} to dispatch the event, C{False} otherwise.
        """
        if self.__condition in (True, False, None):
            return self.__condition
        return self.__condition(event)

#------------------------------------------------------------------------------

    def is_automatic(self):
        """
        @rtype:  bool
        @return: C{True} if the breakpoint has an action callback defined.
        """
        return self.__action is not None

    def is_interactive(self):
        """
        @rtype:  bool
        @return:
            C{True} if the breakpoint doesn't have an action callback defined.
        """
        return self.__action is None

    def get_action(self):
        """
        @rtype:  bool, function
        @return: Returns the action callback for automatic breakpoints.
            Returns C{None} for interactive breakpoints.
        """
        return self.__action

    def set_action(self, action = None):
        """
        Sets a new action callback for the breakpoint.

        @type  action: function
        @param action: (Optional) Action callback function.
        """
        self.__action = action

    def run_action(self, event):
        """
        Executes the breakpoint action callback, if any was set.

        @type  event: L{Event}
        @param event: Debug event triggered by the breakpoint.
        """
        if self.__action is not None:
            return bool( self.__action(event) )
        return True

#------------------------------------------------------------------------------

    def __bad_transition(self, state):
        """
        Raises an C{AssertionError} exception for an invalid state transition.

        @see: L{stateNames}

        @type  state: int
        @param state: Intended breakpoint state.

        @raise Exception: Always.
        """
        statemsg = ""
        oldState = self.stateNames[ self.get_state() ]
        newState = self.stateNames[ state ]
        msg = "Invalid state transition (%s -> %s)" \
              " for breakpoint at address %s"
        msg = msg % (oldState, newState, HexDump.address(self.get_address()))
        raise AssertionError, msg

    def disable(self, aProcess, aThread):
        """
        Transition to L{DISABLED} state.
          - When hit: OneShot S{->} Disabled
          - Forced by user: Enabled, OneShot, Running S{->} Disabled
          - Transition from running state may require special handling
            by the breakpoint implementation class.

        @type  aProcess: L{Process}
        @param aProcess: Process object.

        @type  aThread: L{Thread}
        @param aThread: Thread object.
        """
##        if self.__state not in (self.ENABLED, self.ONESHOT, self.RUNNING):
##            self.__bad_transition(self.DISABLED)
        self.__state = self.DISABLED

    def enable(self, aProcess, aThread):
        """
        Transition to L{ENABLED} state.
          - When hit: Running S{->} Enabled
          - Forced by user: Disabled, Running S{->} Enabled
          - Transition from running state may require special handling
            by the breakpoint implementation class.

        @type  aProcess: L{Process}
        @param aProcess: Process object.

        @type  aThread: L{Thread}
        @param aThread: Thread object.
        """
##        if self.__state not in (self.DISABLED, self.RUNNING):
##            self.__bad_transition(self.ENABLED)
        self.__state = self.ENABLED

    def one_shot(self, aProcess, aThread):
        """
        Transition to L{ONESHOT} state.
          - Forced by user: Disabled S{->} OneShot

        @type  aProcess: L{Process}
        @param aProcess: Process object.

        @type  aThread: L{Thread}
        @param aThread: Thread object.
        """
##        if self.__state != self.DISABLED:
##            self.__bad_transition(self.ONESHOT)
        self.__state = self.ONESHOT

    def running(self, aProcess, aThread):
        """
        Transition to L{RUNNING} state.
          - When hit: Enabled S{->} Running

        @type  aProcess: L{Process}
        @param aProcess: Process object.

        @type  aThread: L{Thread}
        @param aThread: Thread object.
        """
        if self.__state != self.ENABLED:
            self.__bad_transition(self.RUNNING)
        self.__state = self.RUNNING

    def hit(self, event):
        """
        Notify a breakpoint that it's been hit.
        This triggers the corresponding state transition.

        @see: L{disable}, L{enable}, L{one_shot}, L{running}

        @type  event: L{Event}
        @param event: Debug event to handle (depends on the breakpoint type).

        @raise AssertionError: Disabled breakpoints can't be hit.
        """
        aProcess = event.get_process()
        aThread  = event.get_thread()
        state    = self.get_state()

        if state == self.ENABLED:
            self.running(aProcess, aThread)

        elif state == self.RUNNING:
            self.enable(aProcess, aThread)

        elif state == self.ONESHOT:
            self.disable(aProcess, aThread)

        elif state == self.DISABLED:
            # this should not happen
            msg = "Hit a disabled breakpoint at address %s"
            msg = msg % HexDump.address( self.get_address() )
            raise AssertionError, msg

#==============================================================================

# XXX TODO
# Check if the user is trying to set a code breakpoint on a memory mapped file,
# so we don't end up writing the int3 instruction in the file by accident.
# It's probably enough to change the page protection to copy-on-write.

class CodeBreakpoint (Breakpoint):
    """
    Code execution breakpoints (using an int3 opcode).

    @see: L{Debug.break_at}

    @type bpInstruction: str
    @cvar bpInstruction: Breakpoint instruction for the current processor.
    """

    typeName = 'code breakpoint'

    if System.arch in ('i386', 'amd64'):
        bpInstruction = '\xCC'      # int 3

    def __init__(self, address, condition = True, action = None):
        """
        Code breakpoint object.

        @see: L{Breakpoint.__init__}

        @type  address: int
        @param address: Memory address for breakpoint.

        @type  condition: function
        @param condition: (Optional) Condition callback function.

        @type  action: function
        @param action: (Optional) Action callback function.
        """
        if System.arch not in ('i386', 'amd64'):
            msg = "Code breakpoints not supported for %s" % System.arch
            raise NotImplementedError, msg
        Breakpoint.__init__(self, address, len(self.bpInstruction),
                            condition, action)
        self.__previousValue = self.bpInstruction

    def __set_bp(self, aProcess):
        """
        Writes a breakpoint instruction at the target address.

        @type  aProcess: L{Process}
        @param aProcess: Process object.
        """
        address = self.get_address()
        # XXX maybe if the previous value is \xCC we shouldn't trust it?
        self.__previousValue = aProcess.read(address, len(self.bpInstruction))
        aProcess.write(address, self.bpInstruction)

    def __clear_bp(self, aProcess):
        """
        Restores the original byte at the target address.

        @type  aProcess: L{Process}
        @param aProcess: Process object.
        """
        # Only restore the previous value if the int3 is still there.
        address = self.get_address()
        currentValue = aProcess.read(address, len(self.bpInstruction))
        if currentValue == self.bpInstruction:
            aProcess.write(self.get_address(), self.__previousValue)
        else:
            self.__previousValue = currentValue

    def disable(self, aProcess, aThread):
        if not self.is_disabled() and not self.is_running():
            self.__clear_bp(aProcess)
        super(CodeBreakpoint, self).disable(aProcess, aThread)

    def enable(self, aProcess, aThread):
        if not self.is_enabled() and not self.is_one_shot():
            self.__set_bp(aProcess)
        super(CodeBreakpoint, self).enable(aProcess, aThread)

    def one_shot(self, aProcess, aThread):
        if not self.is_enabled() and not self.is_one_shot():
            self.__set_bp(aProcess)
        super(CodeBreakpoint, self).one_shot(aProcess, aThread)

    # FIXME race condition here (however unlikely)
    # If another thread runs on over the target address while
    # the breakpoint is in RUNNING state, we'll miss it. There
    # is a solution to this but it's somewhat complicated, so
    # I'm leaving it for the next version of the debugger. :(
    def running(self, aProcess, aThread):
        self.__clear_bp(aProcess)
        aThread.set_tf()
        super(CodeBreakpoint, self).running(aProcess, aThread)

#==============================================================================

# TODO:
# * If the original page was already a guard page, the exception should be
#   passed to the debugee instead of being handled by the debugger.
# * If the original page was already a guard page, it should NOT be converted
#   to a no-access page when disabling the breakpoint.
# * If the page permissions were modified after the breakpoint was enabled,
#   no change should be done on them when disabling the breakpoint. For this
#   we need to remember the original page permissions instead of blindly
#   setting and clearing the guard page bit on them.

class PageBreakpoint (Breakpoint):
    """
    Page access breakpoint (using guard pages).

    @see: L{Debug.watch_buffer}
    """

    typeName = 'page breakpoint'

#------------------------------------------------------------------------------

    def __init__(self, address, pages = 1, condition = True, action = None):
        """
        Page breakpoint object.

        @see: L{Breakpoint.__init__}

        @type  address: int
        @param address: Memory address for breakpoint.

        @type  pages: int
        @param address: Size of breakpoint in pages.

        @type  condition: function
        @param condition: (Optional) Condition callback function.

        @type  action: function
        @param action: (Optional) Action callback function.
        """
        Breakpoint.__init__(self, address, pages * System.pageSize,  condition,
                                                                        action)
##        if (address & 0x00000FFF) != 0:
        floordiv_align = long(address) // long(System.pageSize)
        truediv_align  = float(address) / float(System.pageSize)
        if floordiv_align != truediv_align:
            msg   = "Address of page breakpoint "               \
                    "must be aligned to a page size boundary "  \
                    "(value %s received)" % HexDump.address(address)
            raise ValueError, msg

    def get_size_in_pages(self):
        """
        @rtype:  int
        @return: The size in pages of the breakpoint.
        """
        # The size is always a multiple of the page size.
        return self.get_size() // System.pageSize

    def __set_bp(self, aProcess):
        """
        Sets the target pages as guard pages.

        @type  aProcess: L{Process}
        @param aProcess: Process object.
        """
        lpAddress    = self.get_address()
        dwSize       = self.get_size()
        flNewProtect = aProcess.mquery(lpAddress).Protect
        flNewProtect = flNewProtect | win32.PAGE_GUARD
        aProcess.mprotect(lpAddress, dwSize, flNewProtect)

    def __clear_bp(self, aProcess):
        """
        Restores the original permissions of the target pages.

        @type  aProcess: L{Process}
        @param aProcess: Process object.
        """
        lpAddress    = self.get_address()
        flNewProtect = aProcess.mquery(lpAddress).Protect
        flNewProtect = flNewProtect & (0xFFFFFFFF ^ win32.PAGE_GUARD)   # DWORD
        aProcess.mprotect(lpAddress, self.get_size(), flNewProtect)

    def disable(self, aProcess, aThread):
        if not self.is_disabled():
            self.__clear_bp(aProcess)
        super(PageBreakpoint, self).disable(aProcess, aThread)

    def enable(self, aProcess, aThread):
        if System.arch not in ('i386', 'amd64'):
            msg = "Only one-shot page breakpoints are supported for %s"
            raise NotImplementedError, msg % System.arch
        if not self.is_enabled() and not self.is_one_shot():
            self.__set_bp(aProcess)
        super(PageBreakpoint, self).enable(aProcess, aThread)

    def one_shot(self, aProcess, aThread):
        if not self.is_enabled() and not self.is_one_shot():
            self.__set_bp(aProcess)
        super(PageBreakpoint, self).one_shot(aProcess, aThread)

    def running(self, aProcess, aThread):
        aThread.set_tf()
        super(PageBreakpoint, self).running(aProcess, aThread)

#==============================================================================

class HardwareBreakpoint (Breakpoint):
    """
    Hardware breakpoint (using debug registers).

    @see: L{Debug.watch_variable}
    @group Trigger flags:
        BREAK_ON_EXECUTION, BREAK_ON_WRITE, BREAK_ON_ACCESS, BREAK_ON_IO_ACCESS
    @group Watch size flags:
        WATCH_BYTE, WATCH_WORD, WATCH_DWORD, WATCH_QWORD

    @type BREAK_ON_EXECUTION: int
    @cvar BREAK_ON_EXECUTION: Break on execution.

    @type BREAK_ON_WRITE: int
    @cvar BREAK_ON_WRITE: Break on write.

    @type BREAK_ON_ACCESS: int
    @cvar BREAK_ON_ACCESS: Break on read or write.

    @type BREAK_ON_IO_ACCESS: int
    @cvar BREAK_ON_IO_ACCESS: Break on I/O port access.

    @type WATCH_BYTE: int
    @cvar WATCH_BYTE: Watch a byte.

    @type WATCH_WORD: int
    @cvar WATCH_WORD: Watch a word.

    @type WATCH_DWORD: int
    @cvar WATCH_DWORD: Watch a double word.

    @type WATCH_QWORD: int
    @cvar WATCH_QWORD: Watch one quad word.

    @type validTriggers: tuple
    @cvar validTriggers: Valid trigger flag values.

    @type validWatchSizes: tuple
    @cvar validWatchSizes: Valid watch flag values.
    """

    typeName = 'hardware breakpoint'

    BREAK_ON_EXECUTION  = DebugRegister.BREAK_ON_EXECUTION
    BREAK_ON_WRITE      = DebugRegister.BREAK_ON_WRITE
    BREAK_ON_ACCESS     = DebugRegister.BREAK_ON_ACCESS
    BREAK_ON_IO_ACCESS  = DebugRegister.BREAK_ON_IO_ACCESS

    WATCH_BYTE  = DebugRegister.WATCH_BYTE
    WATCH_WORD  = DebugRegister.WATCH_WORD
    WATCH_DWORD = DebugRegister.WATCH_DWORD
    WATCH_QWORD = DebugRegister.WATCH_QWORD

    validTriggers = (
        BREAK_ON_EXECUTION,
        BREAK_ON_WRITE,
        BREAK_ON_ACCESS,
        BREAK_ON_IO_ACCESS,     # not supported by hardware
    )

    validWatchSizes = (
        WATCH_BYTE,
        WATCH_WORD,
        WATCH_DWORD,
        WATCH_QWORD,
    )

    def __init__(self, address,                 triggerFlag = BREAK_ON_ACCESS,
                                                   sizeFlag = WATCH_DWORD,
                                                  condition = True,
                                                     action = None):
        """
        Hardware breakpoint object.

        @see: L{Breakpoint.__init__}

        @type  address: int
        @param address: Memory address for breakpoint.

        @type  triggerFlag: int
        @param triggerFlag: Trigger of breakpoint. Must be one of the following:

             - L{BREAK_ON_EXECUTION}

               Break on code execution.

             - L{BREAK_ON_WRITE}

               Break on memory read or write.

             - L{BREAK_ON_ACCESS}

               Break on memory write.

        @type  sizeFlag: int
        @param sizeFlag: Size of breakpoint. Must be one of the following:

             - L{WATCH_BYTE}

               One (1) byte in size.

             - L{WATCH_WORD}

               Two (2) bytes in size.

             - L{WATCH_DWORD}

               Four (4) bytes in size.

             - L{WATCH_QWORD}

               Eight (8) bytes in size.

        @type  condition: function
        @param condition: (Optional) Condition callback function.

        @type  action: function
        @param action: (Optional) Action callback function.
        """
        if System.arch not in ('i386', 'amd64'):
            msg = "Hardware breakpoints not supported for %s" % System.arch
            raise NotImplementedError, msg
        if   sizeFlag == self.WATCH_BYTE:
            size = 1
        elif sizeFlag == self.WATCH_WORD:
            size = 2
        elif sizeFlag == self.WATCH_DWORD:
            size = 4
        elif sizeFlag == self.WATCH_QWORD:
            size = 8
        else:
            msg = "Invalid size flag for hardware breakpoint (%s)"
            msg = msg % repr(sizeFlag)
            raise ValueError, msg

        if triggerFlag not in self.validTriggers:
            msg = "Invalid trigger flag for hardware breakpoint (%s)"
            msg = msg % repr(triggerFlag)
            raise ValueError, msg

        Breakpoint.__init__(self, address, size, condition, action)
        self.__trigger  = triggerFlag
        self.__watch    = sizeFlag
        self.__slot     = None

    def __clear_bp(self, aThread):
        """
        Clears this breakpoint from the debug registers.

        @type  aThread: L{Thread}
        @param aThread: Thread object.
        """
        if self.__slot is not None:
            aThread.suspend()
            try:
                ctx = aThread.get_context(win32.CONTEXT_DEBUG_REGISTERS)
                DebugRegister.clear_bp(ctx, self.__slot)
                aThread.set_context(ctx)
                self.__slot = None
            finally:
                aThread.resume()

    def __set_bp(self, aThread):
        """
        Sets this breakpoint in the debug registers.

        @type  aThread: L{Thread}
        @param aThread: Thread object.
        """
        if self.__slot is None:
            aThread.suspend()
            try:
                ctx = aThread.get_context(win32.CONTEXT_DEBUG_REGISTERS)
                self.__slot = DebugRegister.find_slot(ctx)
                if self.__slot is None:
                    msg = "No available hardware breakpoint slots for thread ID %d"
                    msg = msg % aThread.get_tid()
                    raise RuntimeError, msg
                DebugRegister.set_bp(ctx, self.__slot, self.get_address(),
                                                       self.__trigger, self.__watch)
                aThread.set_context(ctx)
            finally:
                aThread.resume()

    def get_slot(self):
        """
        @rtype:  int
        @return: The debug register number used by this breakpoint,
            or C{None} if the breakpoint is not active.
        """
        return self.__slot

    def get_trigger(self):
        """
        @see: L{validTriggers}
        @rtype:  int
        @return: The breakpoint trigger flag.
        """
        return self.__trigger

    def get_watch(self):
        """
        @see: L{validWatchSizes}
        @rtype:  int
        @return: The breakpoint watch flag.
        """
        return self.__watch

    def disable(self, aProcess, aThread):
        if not self.is_disabled():
            self.__clear_bp(aThread)
        super(HardwareBreakpoint, self).disable(aProcess, aThread)

    def enable(self, aProcess, aThread):
        if not self.is_enabled() and not self.is_one_shot():
            self.__set_bp(aThread)
        super(HardwareBreakpoint, self).enable(aProcess, aThread)

    def one_shot(self, aProcess, aThread):
        if not self.is_enabled() and not self.is_one_shot():
            self.__set_bp(aThread)
        super(HardwareBreakpoint, self).one_shot(aProcess, aThread)

    def running(self, aProcess, aThread):
        self.__clear_bp(aThread)
        super(HardwareBreakpoint, self).running(aProcess, aThread)
        aThread.set_tf()

#==============================================================================

# XXX FIXME
#
# Functions hooks, as they are implemented now, don't work correctly for
# recursive functions. The problem is we don't know when to remove the
# breakpoint at the return address. Also there could be more than one return
# address.
#
# One possible solution would involve dictionary of lists, where the key
# would be the thread ID and the value a stack of return addresses. But I
# still don't know what to do if the "wrong" return address is hit for some
# reason (maybe check the stack pointer?). Or if both a code and a hardware
# breakpoint are hit simultaneously.
#
# For now, the workaround for the user is to set only the "pre" callback for
# functions that are known to be recursive.
#
# Hooks may also behave oddly if the return address is overwritten by a buffer
# overflow bug. But it's probably a minor issue since when you're fuzzing a
# function for overflows you're usually not interested in the return value
# anyway.

# XXX TODO
# The assumption that all parameters are DWORDs and all we need is the count
# is wrong for 64 bit Windows. Perhaps a better scheme is in order? Ideally
# it should be kept compatible with previous versions.

class Hook (object):
    """
    Used by L{Debug.hook_function}.

    This class acts as an action callback for code breakpoints set at the
    beginning of a function. It automatically retrieves the parameters from
    the stack, sets a breakpoint at the return address and retrieves the
    return value from the function call.

    @type useHardwareBreakpoints: bool
    @cvar useHardwareBreakpoints: C{True} to try to use hardware breakpoints,
        C{False} otherwise.
    """

    # XXX FIXME
    #
    # Hardware breakpoints don't work in VirtualBox. Maybe there should be a
    # way to autodetect VirtualBox and tell Hook objects not to use them.
    #
    # For now the workaround is to manually set this variable to False when
    # WinAppDbg is installed in a virtual machine.
    #
    useHardwareBreakpoints = True

    def __init__(self, preCB = None, postCB = None, paramCount = 0):
        """
        @type  preCB: function
        @param preCB: (Optional) Callback triggered on function entry.

            The signature for the callback can be something like this::

                def pre_LoadLibraryEx(event, *params):
                    ra   = params[0]        # return address
                    argv = params[1:]       # function parameters

                    # (...)

            But if you passed the right number of arguments, you can also
            use a signature like this::

                def pre_LoadLibraryEx(event, ra, lpFilename, hFile, dwFlags):
                    szFilename = event.get_process().peek_string(lpFilename)

                    # (...)

            In the above example, the value for C{paramCount} would be C{3}.

            Note that the second example assumes all parameters are DWORDs.
            This may not always be so, especially in 64 bits Windows.

        @type  postCB: function
        @param postCB: (Optional) Callback triggered on function exit.

            The signature for the callback would be something like this::

                def post_LoadLibraryEx(event, return_value):

                    # (...)

        @type  paramCount: int
        @param paramCount:
            (Optional) Number of parameters for the C{preCB} callback,
            not counting the return address. Parameters are read from
            the stack and assumed to be DWORDs.
        """
        self.__paramCount = paramCount
        self.__preCB      = preCB
        self.__postCB     = postCB
        self.__paramStack = dict()   # tid -> list of tuple( arg, arg, arg... )

    # By using break_at() to set a process-wide breakpoint on the function's
    # return address, we might hit a race condition when more than one thread
    # is being debugged.
    #
    # Hardware breakpoints should be used instead. But since a thread can run
    # out of those, we need to fall back to this method when needed.

    def __call__(self, event):
        """
        Handles the breakpoint event on entry of the function.

        @type  event: L{ExceptionEvent}
        @param event: Breakpoint hit event.

        @raise WindowsError: An error occured.
        """
        debug = event.debug

        # Get the parameters from the stack.
        dwProcessId = event.get_pid()
        dwThreadId  = event.get_tid()
        aProcess    = event.get_process()
        aThread     = event.get_thread()
        ra          = aProcess.read_pointer( aThread.get_sp() )
        params      = aThread.read_stack_dwords(self.__paramCount,
                                           offset = win32.sizeof(win32.LPVOID))

        # Keep the parameters for later use.
        self.__push_params(dwThreadId, params)

        # If we need to hook the return from the function...
        if self.__postCB is not None:

            # Try to set a one shot hardware breakpoint at the return address.
            useHardwareBreakpoints = self.useHardwareBreakpoints
            if useHardwareBreakpoints:
                try:
                    debug.define_hardware_breakpoint(
                        dwThreadId,
                        ra,
                        event.debug.BP_BREAK_ON_EXECUTION,
                        event.debug.BP_WATCH_BYTE,
                        True,
                        self.__postCallAction_hwbp
                        )
                    debug.enable_one_shot_hardware_breakpoint(dwThreadId, ra)
                except Exception, e:
##                    import traceback        # XXX DEBUG
##                    traceback.print_exc()
                    useHardwareBreakpoints = False

            # If not possible, set a code breakpoint instead.
            if not useHardwareBreakpoints:
                debug.break_at(dwProcessId, ra, self.__postCallAction_codebp)

        # Call the "pre" callback.
        try:
            self.__callHandler(self.__preCB, event, ra, *params)

        # If no "post" callback is defined, forget the parameters.
        finally:
            if self.__postCB is None:
                self.__pop_params(dwThreadId)

    def __postCallAction_hwbp(self, event):
        """
        Handles hardware breakpoint events on return from the function.

        @type  event: L{ExceptionEvent}
        @param event: Single step event.
        """

        # Remove the one shot hardware breakpoint
        # at the return address location in the stack.
        tid     = event.get_tid()
        address = event.breakpoint.get_address()
        event.debug.erase_hardware_breakpoint(tid, address)

        # Call the "post" callback.
        try:
            self.__postCallAction(event)

        # Forget the parameters.
        finally:
            self.__pop_params(tid)

    def __postCallAction_codebp(self, event):
        """
        Handles code breakpoint events on return from the function.

        @type  event: L{ExceptionEvent}
        @param event: Breakpoint hit event.
        """

        # If the breakpoint was accidentally hit by another thread,
        # pass it to the debugger instead of calling the "post" callback.
        #
        # XXX FIXME:
        # I suppose this check will fail under some weird conditions...
        #
        tid = event.get_tid()
        if not self.__paramStack.has_key(tid):
            return True

        # Remove the code breakpoint at the return address.
        pid     = event.get_pid()
        address = event.breakpoint.get_address()
        event.debug.dont_break_at(pid, address)

        # Call the "post" callback.
        try:
            self.__postCallAction(event)

        # Forget the parameters.
        finally:
            self.__pop_params(tid)

    def __postCallAction(self, event):
        """
        Calls the "post" callback.

        @type  event: L{ExceptionEvent}
        @param event: Breakpoint hit event.
        """
        aThread = event.get_thread()
        ctx     = aThread.get_context(win32.CONTEXT_INTEGER)
        if win32.CONTEXT.arch == 'i386':
            retval = ctx['Eax']
        elif win32.CONTEXT.arch == 'amd64':
            retval = ctx['Rax']
##        elif win32.CONTEXT.arch == 'ia64':
##            retval = ctx['IntV0']   # r8
        else:
            retval = None
        self.__callHandler(self.__postCB, event, retval)

    def __callHandler(self, callback, event, *params):
        """
        Calls a "pre" or "post" handler, if set.

        @type  callback: function
        @param callback: Callback function to call.

        @type  event: L{ExceptionEvent}
        @param event: Breakpoint hit event.

        @type  params: tuple
        @param params: Parameters for the callback function.
        """
        event.hook = self
        if callback is not None:
            callback(event, *params)

    def __push_params(self, tid, params):
        """
        Remembers the arguments tuple for the last call to the hooked function
        from this thread.

        @type  tid: int
        @param tid: Thread global ID.

        @type  params: tuple( arg, arg, arg... )
        @param params: Tuple of arguments.
        """
        stack = self.__paramStack.get( tid, [] )
        stack.append(params)
        self.__paramStack[tid] = stack

    def __pop_params(self, tid):
        """
        Forgets the arguments tuple for the last call to the hooked function
        from this thread.

        @type  tid: int
        @param tid: Thread global ID.
        """
        stack = self.__paramStack[tid]
        stack.pop()
        if not stack:
            del self.__paramStack[tid]

    def get_params(self, tid):
        """
        Returns the parameters found in the stack when the hooked function
        was last called by this thread.

        @type  tid: int
        @param tid: Thread global ID.

        @rtype:  tuple( arg, arg, arg... )
        @return: Tuple of arguments.
        """
        try:
            params = self.get_params_stack(tid)[-1]
        except IndexError:
            msg = "Hooked function called from thread %d already returned"
            raise IndexError, msg % tid
        return params

    def get_params_stack(self, tid):
        """
        Returns the parameters found in the stack each time the hooked function
        was called by this thread and haven't returned yet.

        @type  tid: int
        @param tid: Thread global ID.

        @rtype:  list of tuple( arg, arg, arg... )
        @return: List of argument tuples.
        """
        try:
            stack = self.__paramStack[tid]
        except KeyError:
            msg = "Hooked function was not called from thread %d"
            raise KeyError, msg % tid
        return stack

    def hook(self, debug, pid, address):
        """
        Installs the function hook at a given process and address.

        @see: L{unhook}

        @warning: Do not call from an function hook callback.

        @type  debug: L{Debug}
        @param debug: Debug object.

        @type  pid: int
        @param pid: Process ID.

        @type  address: int
        @param address: Function address.
        """
        return debug.break_at(pid, address, self)

    def unhook(self, debug, pid, address):
        """
        Removes the function hook at a given process and address.

        @see: L{hook}

        @warning: Do not call from an function hook callback.

        @type  debug: L{Debug}
        @param debug: Debug object.

        @type  pid: int
        @param pid: Process ID.

        @type  address: int
        @param address: Function address.
        """
        return debug.dont_break_at(pid, address)

#------------------------------------------------------------------------------

class ApiHook (Hook):
    """
    Used by L{EventHandler}.

    This class acts as an action callback for code breakpoints set at the
    beginning of a function. It automatically retrieves the parameters from
    the stack, sets a breakpoint at the return address and retrieves the
    return value from the function call.

    @see: L{EventHandler.apiHooks}
    """

    def __init__(self, eventHandler, procName, paramCount = 0):
        """
        @type  eventHandler: L{EventHandler}
        @param eventHandler: Event handler instance.

        @type  procName: str
        @param procName: Procedure name.
            The pre and post callbacks will be deduced from it.

            For example, if the procedure is "LoadLibraryEx" the callback
            routines will be "pre_LoadLibraryEx" and "post_LoadLibraryEx".

            The signature for the callbacks can be something like this::

                def pre_LoadLibraryEx(event, *params):
                    ra   = params[0]        # return address
                    argv = params[1:]       # function parameters

                    # (...)

                def post_LoadLibraryEx(event, return_value):

                    # (...)

            But if you passed the right number of arguments, you can also
            use a signature like this::

                def pre_LoadLibraryEx(event, ra, lpFilename, hFile, dwFlags):
                    szFilename = event.get_process().peek_string(lpFilename)

                    # (...)

            Note that the second example assumes all parameters are DWORDs.
            This may not always be so, especially in 64 bits Windows.

        @type  paramCount: int
        @param paramCount: (Optional) Number of parameters for the callback.
            Parameters are read from the stack and assumed to be DWORDs.
            The first parameter of the pre callback is always the return address.
        """
        self.__procName = procName

        preCB  = getattr(eventHandler, 'pre_%s'  % procName, None)
        postCB = getattr(eventHandler, 'post_%s' % procName, None)
        Hook.__init__(self, preCB, postCB, paramCount)

    def hook(self, debug, pid, modName):
        """
        Installs the API hook on a given process and module.

        @warning: Do not call from an API hook callback.

        @type  debug: L{Debug}
        @param debug: Debug object.

        @type  pid: int
        @param pid: Process ID.

        @type  modName: str
        @param modName: Module name.
        """
        address = debug.resolve_exported_function(pid, modName, self.__procName)
        Hook.hook(self, debug, pid, address)

    def unhook(self, debug, pid, modName):
        """
        Removes the API hook from the given process and module.

        @warning: Do not call from an API hook callback.

        @type  debug: L{Debug}
        @param debug: Debug object.

        @type  pid: int
        @param pid: Process ID.

        @type  modName: str
        @param modName: Module name.
        """
        address = debug.resolve_exported_function(pid, modName, self.__procName)
        Hook.unhook(self, debug, pid, address)

#==============================================================================

class BufferWatch (object):
    """
    Used by L{Debug.watch_buffer}.

    This class acts as a condition callback for page breakpoints.
    It emulates page breakpoints that can overlap and/or take up less
    than a page's size.
    """

    def __init__(self):
        self.__ranges = dict()

    def add(self, address, size, action = None):
        """
        Adds a buffer to the watch object.

        @type  address: int
        @param address: Memory address of buffer to watch.

        @type  size: int
        @param size: Size in bytes of buffer to watch.

        @type  action: function
        @param action: (Optional) Action callback function.

            See L{Debug.define_page_breakpoint} for more details.
        """
        key = (address, address + size)
        if key in self.__ranges:
            msg = "Buffer from %s to %s is already being watched"
            begin = HexDump.address(key[0])
            end   = HexDump.address(key[1])
            raise RuntimeError, msg % (begin, end)
        self.__ranges[key] = action

    def remove(self, address, size):
        """
        Removes a buffer from the watch object.

        @type  address: int
        @param address: Memory address of buffer to stop watching.

        @type  size: int
        @param size: Size in bytes of buffer to stop watching.
        """
        key = (address, address + size)
        if key not in self.__ranges:
            msg = "No buffer watch set at %s-%s"
            begin = HexDump.address(key[0])
            end   = HexDump.address(key[1])
            raise RuntimeError, msg % (begin, end)
        del self.__ranges[key]

    def exists(self, address, size):
        """
        @type  address: int
        @param address: Memory address of buffer being watched.

        @type  size: int
        @param size: Size in bytes of buffer being watched.

        @rtype:  bool
        @return: C{True} if the buffer is being watched, C{False} otherwise.
        """
        key = (address, address + size)
        return key in self.__ranges

    def span(self):
        """
        @rtype:  tuple( int, int )
        @return:
            Base address and size in pages required to watch all the buffers.
        """
        min_start = 0
        max_end   = 0
        for ((start, end), action) in self.__ranges.iteritems():
            if start < min_start:
                min_start = start
            if end > max_end:
                max_end = end
        base  = MemoryAddresses.align_address_to_page_start(min_start)
        size  = max_end - min_start
        pages = MemoryAddresses.get_buffer_size_in_pages(min_start, size)
        return ( base, pages )

    def count(self):
        """
        @rtype:  int
        @return: Number of buffers being watched.
        """
        return len(self.__ranges)

    def __call__(self, event):
        """
        Breakpoint condition callback.

        This method will also call the action callbacks for each
        buffer being watched.

        @type  event: L{ExceptionEvent}
        @param event: Guard page exception event.

        @rtype:  bool
        @return: C{True} if the address being accessed belongs
            to at least one of the buffers that was being watched
            and had no action callback.
        """
        address    = event.get_exception_information(1)
        bCondition = False
        for ((start, end), action) in self.__ranges.iteritems():
            bMatched = ( start <= address < end )
            if bMatched and action is not None:
                action(event)
            else:
                bCondition = bCondition or bMatched
        return bCondition

#==============================================================================

class BreakpointContainer (object):
    """
    Encapsulates the capability to contain Breakpoint objects.

    @group Breakpoints:
        break_at, watch_variable, watch_buffer, hook_function,
        dont_break_at, dont_watch_variable, dont_watch_buffer,
        dont_hook_function, unhook_function

    @group Stalking:
        stalk_at, stalk_variable, stalk_buffer, stalk_function,
        dont_stalk_at, dont_stalk_variable, dont_stalk_buffer,
        dont_stalk_function

    @group Tracing:
        is_tracing, get_traced_tids,
        start_tracing, stop_tracing,
        start_tracing_process, stop_tracing_process,
        start_tracing_all, stop_tracing_all

    @group Symbols:
        resolve_label, resolve_exported_function

    @group Advanced breakpoint use:
        define_code_breakpoint,
        define_page_breakpoint,
        define_hardware_breakpoint,
        has_code_breakpoint,
        has_page_breakpoint,
        has_hardware_breakpoint,
        get_code_breakpoint,
        get_page_breakpoint,
        get_hardware_breakpoint,
        erase_code_breakpoint,
        erase_page_breakpoint,
        erase_hardware_breakpoint,
        enable_code_breakpoint,
        enable_page_breakpoint,
        enable_hardware_breakpoint,
        enable_one_shot_code_breakpoint,
        enable_one_shot_page_breakpoint,
        enable_one_shot_hardware_breakpoint,
        disable_code_breakpoint,
        disable_page_breakpoint,
        disable_hardware_breakpoint

    @group Listing breakpoints:
        get_all_breakpoints,
        get_all_code_breakpoints,
        get_all_page_breakpoints,
        get_all_hardware_breakpoints,
        get_process_breakpoints,
        get_process_code_breakpoints,
        get_process_page_breakpoints,
        get_process_hardware_breakpoints,
        get_thread_hardware_breakpoints

    @group Batch operations on breakpoints:
        enable_all_breakpoints,
        enable_one_shot_all_breakpoints,
        disable_all_breakpoints,
        erase_all_breakpoints,
        enable_process_breakpoints,
        enable_one_shot_process_breakpoints,
        disable_process_breakpoints,
        erase_process_breakpoints

    @group Event notifications (private):
        notify_guard_page,
        notify_breakpoint,
        notify_single_step,
        notify_exit_thread,
        notify_exit_process

    @group Breakpoint types:
        BP_TYPE_ANY, BP_TYPE_CODE, BP_TYPE_PAGE, BP_TYPE_HARDWARE
    @group Breakpoint states:
        BP_STATE_DISABLED, BP_STATE_ENABLED, BP_STATE_ONESHOT, BP_STATE_RUNNING
    @group Memory breakpoint trigger flags:
        BP_BREAK_ON_EXECUTION, BP_BREAK_ON_WRITE, BP_BREAK_ON_ACCESS
    @group Memory breakpoint size flags:
        BP_WATCH_BYTE, BP_WATCH_WORD, BP_WATCH_DWORD, BP_WATCH_QWORD

    @type BP_TYPE_ANY: int
    @cvar BP_TYPE_ANY: To get all breakpoints
    @type BP_TYPE_CODE: int
    @cvar BP_TYPE_CODE: To get code breakpoints only
    @type BP_TYPE_PAGE: int
    @cvar BP_TYPE_PAGE: To get page breakpoints only
    @type BP_TYPE_HARDWARE: int
    @cvar BP_TYPE_HARDWARE: To get hardware breakpoints only

    @type BP_STATE_DISABLED: int
    @cvar BP_STATE_DISABLED: Breakpoint is disabled.
    @type BP_STATE_ENABLED: int
    @cvar BP_STATE_ENABLED: Breakpoint is enabled.
    @type BP_STATE_ONESHOT: int
    @cvar BP_STATE_ONESHOT: Breakpoint is enabled for one shot.
    @type BP_STATE_RUNNING: int
    @cvar BP_STATE_RUNNING: Breakpoint is running (recently hit).

    @type BP_BREAK_ON_EXECUTION: int
    @cvar BP_BREAK_ON_EXECUTION: Break on code execution.
    @type BP_BREAK_ON_WRITE: int
    @cvar BP_BREAK_ON_WRITE: Break on memory write.
    @type BP_BREAK_ON_ACCESS: int
    @cvar BP_BREAK_ON_ACCESS: Break on memory read or write.
    """

    # Breakpoint types
    BP_TYPE_ANY             = 0     # to get all breakpoints
    BP_TYPE_CODE            = 1
    BP_TYPE_PAGE            = 2
    BP_TYPE_HARDWARE        = 3

    # Breakpoint states
    BP_STATE_DISABLED       = Breakpoint.DISABLED
    BP_STATE_ENABLED        = Breakpoint.ENABLED
    BP_STATE_ONESHOT        = Breakpoint.ONESHOT
    BP_STATE_RUNNING        = Breakpoint.RUNNING

    # Memory breakpoint trigger flags
    BP_BREAK_ON_EXECUTION   = HardwareBreakpoint.BREAK_ON_EXECUTION
    BP_BREAK_ON_WRITE       = HardwareBreakpoint.BREAK_ON_WRITE
    BP_BREAK_ON_IO_ACCESS   = HardwareBreakpoint.BREAK_ON_IO_ACCESS
    BP_BREAK_ON_ACCESS      = HardwareBreakpoint.BREAK_ON_ACCESS

    # Memory breakpoint size flags
    BP_WATCH_BYTE           = HardwareBreakpoint.WATCH_BYTE
    BP_WATCH_WORD           = HardwareBreakpoint.WATCH_WORD
    BP_WATCH_QWORD          = HardwareBreakpoint.WATCH_QWORD
    BP_WATCH_DWORD          = HardwareBreakpoint.WATCH_DWORD

    def __init__(self):
        self.__codeBP     = dict()  # (pid, address) -> CodeBreakpoint
        self.__pageBP     = dict()  # (pid, address) -> PageBreakpoint
        self.__hardwareBP = dict()  # tid -> [ HardwareBreakpoint ]
        self.__runningBP  = dict()  # tid -> set( Breakpoint )
        self.__tracing    = set()   # set( tid )

#------------------------------------------------------------------------------

    def __has_running_bp(self, tid):
        return tid in self.__runningBP and self.__runningBP[tid]

    def __pop_running_bp(self, tid):
        return self.__runningBP[tid].pop()

    def __add_running_bp(self, tid, bp):
        if tid not in self.__runningBP:
            self.__runningBP[tid] = set()
        self.__runningBP[tid].add(bp)

    def __del_running_bp(self, tid, bp):
        self.__runningBP[tid].remove(bp)
        if not self.__runningBP[tid]:
            del self.__runningBP[tid]

    def __del_running_bp_from_all_threads(self, bp):
        for (tid, bpset) in self.__runningBP.iteritems():
            if bp in bpset:
                bpset.remove(bp)
                self.system.get_thread(tid).clear_tf()

    def __cleanup_thread(self, event):
        """
        Auxiliary method for L{notify_exit_thread} and L{notify_exit_process}.
        """
        tid = event.get_tid()
        if tid in list(self.__runningBP):
            del self.__runningBP[tid]
        if tid in list(self.__hardwareBP):
            del self.__hardwareBP[tid]
        if tid in self.__tracing:
            self.__tracing.remove(tid)

    def __cleanup_process(self, event):
        """
        Auxiliary method for L{notify_exit_process}.
        """
        pid     = event.get_pid()
        process = event.get_process()
        for (bp_pid, bp_address) in self.__codeBP.items():
            if bp_pid == pid:
                del self.__codeBP[(bp_pid, bp_address)]
        for (bp_pid, bp_address) in self.__pageBP.items():
            if bp_pid == pid:
                del self.__pageBP[(bp_pid, bp_address)]

    def __cleanup_module(self, event):
        """
        Auxiliary method for L{notify_unload_dll}.
        """
        pid     = event.get_pid()
        process = event.get_process()
        module  = event.get_module()
        for tid in process.iter_thread_ids():
            thread = process.get_thread(tid)
            if tid in self.__runningBP:
                bplist = list(self.__runningBP[tid])
                for bp in bplist:
                    bp_address = bp.get_address()
                    if process.get_module_at_address(bp_address) == module:
                        bp.disable(process, thread)
                        self.__runningBP[tid].remove(bp)
            if tid in self.__hardwareBP:
                bplist = list(self.__hardwareBP[tid])
                for bp in bplist:
                    bp_address = bp.get_address()
                    if process.get_module_at_address(bp_address) == module:
                        bp.disable(process, thread)
                        self.__hardwareBP[tid].remove(bp)
        for (bp_pid, bp_address) in self.__codeBP.items():
            if bp_pid == pid:
                if process.get_module_at_address(bp_address) == module:
                    del self.__codeBP[(bp_pid, bp_address)]
        for (bp_pid, bp_address) in self.__pageBP.items():
            if bp_pid == pid:
                if process.get_module_at_address(bp_address) == module:
                    del self.__pageBP[(bp_pid, bp_address)]

#------------------------------------------------------------------------------

    def define_code_breakpoint(self, dwProcessId, address,   condition = True,
                                                                action = None):
        """
        Creates a disabled code breakpoint at the given address.

        @see:
            L{has_code_breakpoint},
            L{get_code_breakpoint},
            L{enable_code_breakpoint},
            L{enable_one_shot_code_breakpoint},
            L{disable_code_breakpoint},
            L{erase_code_breakpoint}

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of the code instruction to break at.

        @type  condition: function
        @param condition: (Optional) Condition callback function.

            The callback signature is::

                def condition_callback(event):
                    return True     # returns True or False

            Where B{event} is an L{Event} object,
            and the return value is a boolean
            (C{True} to dispatch the event, C{False} otherwise).

        @type  action: function
        @param action: (Optional) Action callback function.
            If specified, the event is handled by this callback instead of
            being dispatched normally.

            The callback signature is::

                def action_callback(event):
                    pass        # no return value

            Where B{event} is an L{Event} object,
            and the return value is a boolean
            (C{True} to dispatch the event, C{False} otherwise).

        @rtype:  L{CodeBreakpoint}
        @return: The code breakpoint object.
        """
        process = self.system.get_process(dwProcessId)
        bp = CodeBreakpoint(address, condition, action)

        key = (dwProcessId, bp.get_address())
        if key in self.__codeBP:
            msg = "Already exists (PID %d) : %r"
            raise KeyError, msg % (dwProcessId, self.__codeBP[key])
        self.__codeBP[key] = bp
        return bp

    def define_page_breakpoint(self, dwProcessId, address,       pages = 1,
                                                             condition = True,
                                                                action = None):
        """
        Creates a disabled page breakpoint at the given address.

        @see:
            L{has_page_breakpoint},
            L{get_page_breakpoint},
            L{enable_page_breakpoint},
            L{enable_one_shot_page_breakpoint},
            L{disable_page_breakpoint},
            L{erase_page_breakpoint}

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of the first page to watch.

        @type  pages: int
        @param pages: Number of pages to watch.

        @type  condition: function
        @param condition: (Optional) Condition callback function.

            The callback signature is::

                def condition_callback(event):
                    return True     # returns True or False

            Where B{event} is an L{Event} object,
            and the return value is a boolean
            (C{True} to dispatch the event, C{False} otherwise).

        @type  action: function
        @param action: (Optional) Action callback function.
            If specified, the event is handled by this callback instead of
            being dispatched normally.

            The callback signature is::

                def action_callback(event):
                    pass        # no return value

            Where B{event} is an L{Event} object,
            and the return value is a boolean
            (C{True} to dispatch the event, C{False} otherwise).

        @rtype:  L{PageBreakpoint}
        @return: The page breakpoint object.
        """
        process = self.system.get_process(dwProcessId)
        bp      = PageBreakpoint(address, pages, condition, action)
        begin   = bp.get_address()
        end     = begin + bp.get_size()

        for address in xrange(begin, end, System.pageSize):
            key = (dwProcessId, address)
            if key in self.__pageBP:
                msg = "Already exists (PID %d) : %r"
                msg = msg % (dwProcessId, self.__pageBP[key])
                raise KeyError, msg

        for address in xrange(begin, end, System.pageSize):
            key = (dwProcessId, address)
            self.__pageBP[key] = bp
        return bp

    def define_hardware_breakpoint(self, dwThreadId, address,
                                              triggerFlag = BP_BREAK_ON_ACCESS,
                                                 sizeFlag = BP_WATCH_DWORD,
                                                condition = True,
                                                   action = None):
        """
        Creates a disabled hardware breakpoint at the given address.

        @see:
            L{has_hardware_breakpoint},
            L{get_hardware_breakpoint},
            L{enable_hardware_breakpoint},
            L{enable_one_shot_hardware_breakpoint},
            L{disable_hardware_breakpoint},
            L{erase_hardware_breakpoint}

        @note:
            Hardware breakpoints do not seem to work properly on VirtualBox.
            See U{http://www.virtualbox.org/ticket/477}.

        @type  dwThreadId: int
        @param dwThreadId: Thread global ID.

        @type  address: int
        @param address: Memory address to watch.

        @type  triggerFlag: int
        @param triggerFlag: Trigger of breakpoint. Must be one of the following:

             - L{BP_BREAK_ON_EXECUTION}

               Break on code execution.

             - L{BP_BREAK_ON_WRITE}

               Break on memory read or write.

             - L{BP_BREAK_ON_ACCESS}

               Break on memory write.

        @type  sizeFlag: int
        @param sizeFlag: Size of breakpoint. Must be one of the following:

             - L{BP_WATCH_BYTE}

               One (1) byte in size.

             - L{BP_WATCH_WORD}

               Two (2) bytes in size.

             - L{BP_WATCH_DWORD}

               Four (4) bytes in size.

             - L{BP_WATCH_QWORD}

               Eight (8) bytes in size.

        @type  condition: function
        @param condition: (Optional) Condition callback function.

            The callback signature is::

                def condition_callback(event):
                    return True     # returns True or False

            Where B{event} is an L{Event} object,
            and the return value is a boolean
            (C{True} to dispatch the event, C{False} otherwise).

        @type  action: function
        @param action: (Optional) Action callback function.
            If specified, the event is handled by this callback instead of
            being dispatched normally.

            The callback signature is::

                def action_callback(event):
                    pass        # no return value

            Where B{event} is an L{Event} object,
            and the return value is a boolean
            (C{True} to dispatch the event, C{False} otherwise).

        @rtype:  L{HardwareBreakpoint}
        @return: The hardware breakpoint object.
        """
        thread  = self.system.get_thread(dwThreadId)
        bp      = HardwareBreakpoint(address, triggerFlag, sizeFlag, condition,
                                                                        action)
        begin   = bp.get_address()
        end     = begin + bp.get_size()

        if dwThreadId in self.__hardwareBP:
            bpSet = self.__hardwareBP[dwThreadId]
            for oldbp in bpSet:
                old_begin = oldbp.get_address()
                old_end   = old_begin + oldbp.get_size()
                if MemoryAddresses.do_ranges_intersect(begin, end, old_begin,
                                                                     old_end):
                    msg = "Already exists (TID %d) : %r" % (dwThreadId, oldbp)
                    raise KeyError, msg
        else:
            bpSet = set()
            self.__hardwareBP[dwThreadId] = bpSet
        bpSet.add(bp)
        return bp

#------------------------------------------------------------------------------

    def has_code_breakpoint(self, dwProcessId, address):
        """
        Checks if a code breakpoint is defined at the given address.

        @see:
            L{define_code_breakpoint},
            L{get_code_breakpoint},
            L{erase_code_breakpoint},
            L{enable_code_breakpoint},
            L{enable_one_shot_code_breakpoint},
            L{disable_code_breakpoint}

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of breakpoint.

        @rtype:  bool
        @return: C{True} if the breakpoint is defined, C{False} otherwise.
        """
        return (dwProcessId, address) in self.__codeBP

    def has_page_breakpoint(self, dwProcessId, address):
        """
        Checks if a page breakpoint is defined at the given address.

        @see:
            L{define_page_breakpoint},
            L{get_page_breakpoint},
            L{erase_page_breakpoint},
            L{enable_page_breakpoint},
            L{enable_one_shot_page_breakpoint},
            L{disable_page_breakpoint}

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of breakpoint.

        @rtype:  bool
        @return: C{True} if the breakpoint is defined, C{False} otherwise.
        """
        return (dwProcessId, address) in self.__pageBP

    def has_hardware_breakpoint(self, dwThreadId, address):
        """
        Checks if a hardware breakpoint is defined at the given address.

        @see:
            L{define_hardware_breakpoint},
            L{get_hardware_breakpoint},
            L{erase_hardware_breakpoint},
            L{enable_hardware_breakpoint},
            L{enable_one_shot_hardware_breakpoint},
            L{disable_hardware_breakpoint}

        @type  dwThreadId: int
        @param dwThreadId: Thread global ID.

        @type  address: int
        @param address: Memory address of breakpoint.

        @rtype:  bool
        @return: C{True} if the breakpoint is defined, C{False} otherwise.
        """
        if dwThreadId in self.__hardwareBP:
            bpSet = self.__hardwareBP[dwThreadId]
            for bp in bpSet:
                if bp.get_address() == address:
                    return True
        return False

#------------------------------------------------------------------------------

    def get_code_breakpoint(self, dwProcessId, address):
        """
        Returns the internally used breakpoint object,
        for the code breakpoint defined at the given address.

        @warning: It's usually best to call the L{Debug} methods
            instead of accessing the breakpoint objects directly.

        @see:
            L{define_code_breakpoint},
            L{has_code_breakpoint},
            L{enable_code_breakpoint},
            L{enable_one_shot_code_breakpoint},
            L{disable_code_breakpoint},
            L{erase_code_breakpoint}

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address where the breakpoint is defined.

        @rtype:  L{CodeBreakpoint}
        @return: The code breakpoint object.
        """
        key = (dwProcessId, address)
        if key not in self.__codeBP:
            msg = "No breakpoint at process %d, address %s"
            address = HexDump.address(address)
            raise KeyError, msg % (dwProcessId, address)
        return self.__codeBP[key]

    def get_page_breakpoint(self, dwProcessId, address):
        """
        Returns the internally used breakpoint object,
        for the page breakpoint defined at the given address.

        @warning: It's usually best to call the L{Debug} methods
            instead of accessing the breakpoint objects directly.

        @see:
            L{define_page_breakpoint},
            L{has_page_breakpoint},
            L{enable_page_breakpoint},
            L{enable_one_shot_page_breakpoint},
            L{disable_page_breakpoint},
            L{erase_page_breakpoint}

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address where the breakpoint is defined.

        @rtype:  L{PageBreakpoint}
        @return: The page breakpoint object.
        """
        key = (dwProcessId, address)
        if key not in self.__pageBP:
            msg = "No breakpoint at process %d, address %s"
            address = HexDump.addresS(address)
            raise KeyError, msg % (dwProcessId, address)
        return self.__pageBP[key]

    def get_hardware_breakpoint(self, dwThreadId, address):
        """
        Returns the internally used breakpoint object,
        for the code breakpoint defined at the given address.

        @warning: It's usually best to call the L{Debug} methods
            instead of accessing the breakpoint objects directly.

        @see:
            L{define_hardware_breakpoint},
            L{has_hardware_breakpoint},
            L{get_code_breakpoint},
            L{enable_hardware_breakpoint},
            L{enable_one_shot_hardware_breakpoint},
            L{disable_hardware_breakpoint},
            L{erase_hardware_breakpoint}

        @type  dwThreadId: int
        @param dwThreadId: Thread global ID.

        @type  address: int
        @param address: Memory address where the breakpoint is defined.

        @rtype:  L{HardwareBreakpoint}
        @return: The hardware breakpoint object.
        """
        if dwThreadId not in self.__hardwareBP:
            msg = "No hardware breakpoints set for thread %d"
            raise KeyError, msg % dwThreadId
        for bp in self.__hardwareBP[dwThreadId]:
            if bp.is_here(address):
                return bp
        msg = "No hardware breakpoint at thread %d, address %s"
        raise KeyError, msg % (dwThreadId, HexDump.address(address))

#------------------------------------------------------------------------------

    def enable_code_breakpoint(self, dwProcessId, address):
        """
        Enables the code breakpoint at the given address.

        @see:
            L{define_code_breakpoint},
            L{has_code_breakpoint},
            L{enable_one_shot_code_breakpoint},
            L{disable_code_breakpoint}
            L{erase_code_breakpoint},

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        p  = self.system.get_process(dwProcessId)
        bp = self.get_code_breakpoint(dwProcessId, address)
        if bp.is_running():
            self.__del_running_bp_from_all_threads(bp)
        bp.enable(p, None)        # XXX HACK thread is not used

    def enable_page_breakpoint(self, dwProcessId, address):
        """
        Enables the page breakpoint at the given address.

        @see:
            L{define_page_breakpoint},
            L{has_page_breakpoint},
            L{get_page_breakpoint},
            L{enable_one_shot_page_breakpoint},
            L{disable_page_breakpoint}
            L{erase_page_breakpoint},

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        p  = self.system.get_process(dwProcessId)
        bp = self.get_page_breakpoint(dwProcessId, address)
        if bp.is_running():
            self.__del_running_bp_from_all_threads(bp)
        bp.enable(p, None)          # XXX HACK thread is not used

    def enable_hardware_breakpoint(self, dwThreadId, address):
        """
        Enables the hardware breakpoint at the given address.

        @see:
            L{define_hardware_breakpoint},
            L{has_hardware_breakpoint},
            L{get_hardware_breakpoint},
            L{enable_one_shot_hardware_breakpoint},
            L{disable_hardware_breakpoint}
            L{erase_hardware_breakpoint},

        @note: Do not set hardware breakpoints while processing the system
            breakpoint event.

        @type  dwThreadId: int
        @param dwThreadId: Thread global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        t  = self.system.get_thread(dwThreadId)
        bp = self.get_hardware_breakpoint(dwThreadId, address)
        if bp.is_running():
            self.__del_running_bp_from_all_threads(bp)
        bp.enable(None, t)          # XXX HACK process is not used

    def enable_one_shot_code_breakpoint(self, dwProcessId, address):
        """
        Enables the code breakpoint at the given address for only one shot.

        @see:
            L{define_code_breakpoint},
            L{has_code_breakpoint},
            L{get_code_breakpoint},
            L{enable_code_breakpoint},
            L{disable_code_breakpoint}
            L{erase_code_breakpoint},

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        p  = self.system.get_process(dwProcessId)
        bp = self.get_code_breakpoint(dwProcessId, address)
        if bp.is_running():
            self.__del_running_bp_from_all_threads(bp)
        bp.one_shot(p, None)        # XXX HACK thread is not used

    def enable_one_shot_page_breakpoint(self, dwProcessId, address):
        """
        Enables the page breakpoint at the given address for only one shot.

        @see:
            L{define_page_breakpoint},
            L{has_page_breakpoint},
            L{get_page_breakpoint},
            L{enable_page_breakpoint},
            L{disable_page_breakpoint}
            L{erase_page_breakpoint},

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        p  = self.system.get_process(dwProcessId)
        bp = self.get_page_breakpoint(dwProcessId, address)
        if bp.is_running():
            self.__del_running_bp_from_all_threads(bp)
        bp.one_shot(p, None)        # XXX HACK thread is not used

    def enable_one_shot_hardware_breakpoint(self, dwThreadId, address):
        """
        Enables the hardware breakpoint at the given address for only one shot.

        @see:
            L{define_hardware_breakpoint},
            L{has_hardware_breakpoint},
            L{get_hardware_breakpoint},
            L{enable_hardware_breakpoint},
            L{disable_hardware_breakpoint}
            L{erase_hardware_breakpoint},

        @type  dwThreadId: int
        @param dwThreadId: Thread global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        t  = self.system.get_thread(dwThreadId)
        bp = self.get_hardware_breakpoint(dwThreadId, address)
        if bp.is_running():
            self.__del_running_bp_from_all_threads(bp)
        bp.one_shot(None, t)        # XXX HACK process is not used

    def disable_code_breakpoint(self, dwProcessId, address):
        """
        Disables the code breakpoint at the given address.

        @see:
            L{define_code_breakpoint},
            L{has_code_breakpoint},
            L{get_code_breakpoint},
            L{enable_code_breakpoint}
            L{enable_one_shot_code_breakpoint},
            L{erase_code_breakpoint},

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        p  = self.system.get_process(dwProcessId)
        bp = self.get_code_breakpoint(dwProcessId, address)
        if bp.is_running():
            self.__del_running_bp_from_all_threads(bp)
        bp.disable(p, None)     # XXX HACK thread is not used

    def disable_page_breakpoint(self, dwProcessId, address):
        """
        Disables the page breakpoint at the given address.

        @see:
            L{define_page_breakpoint},
            L{has_page_breakpoint},
            L{get_page_breakpoint},
            L{enable_page_breakpoint}
            L{enable_one_shot_page_breakpoint},
            L{erase_page_breakpoint},

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        p  = self.system.get_process(dwProcessId)
        bp = self.get_page_breakpoint(dwProcessId, address)
        if bp.is_running():
            self.__del_running_bp_from_all_threads(bp)
        bp.disable(p, None)     # XXX HACK thread is not used

    def disable_hardware_breakpoint(self, dwThreadId, address):
        """
        Disables the hardware breakpoint at the given address.

        @see:
            L{define_hardware_breakpoint},
            L{has_hardware_breakpoint},
            L{get_hardware_breakpoint},
            L{enable_hardware_breakpoint}
            L{enable_one_shot_hardware_breakpoint},
            L{erase_hardware_breakpoint},

        @type  dwThreadId: int
        @param dwThreadId: Thread global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        t  = self.system.get_thread(dwThreadId)
        p  = t.get_process()
        bp = self.get_hardware_breakpoint(dwThreadId, address)
        if bp.is_running():
            self.__del_running_bp(dwThreadId, bp)
        bp.disable(p, t)

#------------------------------------------------------------------------------

    def erase_code_breakpoint(self, dwProcessId, address):
        """
        Erases the code breakpoint at the given address.

        @see:
            L{define_code_breakpoint},
            L{has_code_breakpoint},
            L{get_code_breakpoint},
            L{enable_code_breakpoint},
            L{enable_one_shot_code_breakpoint},
            L{disable_code_breakpoint}

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        bp = self.get_code_breakpoint(dwProcessId, address)
        if not bp.is_disabled():
            self.disable_code_breakpoint(dwProcessId, address)
        del self.__codeBP[ (dwProcessId, address) ]

    def erase_page_breakpoint(self, dwProcessId, address):
        """
        Erases the page breakpoint at the given address.

        @see:
            L{define_page_breakpoint},
            L{has_page_breakpoint},
            L{get_page_breakpoint},
            L{enable_page_breakpoint},
            L{enable_one_shot_page_breakpoint},
            L{disable_page_breakpoint}

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        bp    = self.get_page_breakpoint(dwProcessId, address)
        begin = bp.get_address()
        end   = begin + bp.get_size()
        if not bp.is_disabled():
            self.disable_page_breakpoint(dwProcessId, address)
        for address in xrange(begin, end, System.pageSize):
            del self.__pageBP[ (dwProcessId, address) ]

    def erase_hardware_breakpoint(self, dwThreadId, address):
        """
        Erases the hardware breakpoint at the given address.

        @see:
            L{define_hardware_breakpoint},
            L{has_hardware_breakpoint},
            L{get_hardware_breakpoint},
            L{enable_hardware_breakpoint},
            L{enable_one_shot_hardware_breakpoint},
            L{disable_hardware_breakpoint}

        @type  dwThreadId: int
        @param dwThreadId: Thread global ID.

        @type  address: int
        @param address: Memory address of breakpoint.
        """
        bp = self.get_hardware_breakpoint(dwThreadId, address)
        if not bp.is_disabled():
            self.disable_hardware_breakpoint(dwThreadId, address)
        bpSet = self.__hardwareBP[dwThreadId]
        bpSet.remove(bp)
        if not bpSet:
            del self.__hardwareBP[dwThreadId]

#------------------------------------------------------------------------------

    def get_all_breakpoints(self):
        """
        Returns all breakpoint objects as a list of tuples.

        Each tuple contains:
         - Process global ID to which the breakpoint applies.
         - Thread global ID to which the breakpoint applies, or C{None}.
         - The L{Breakpoint} object itself.

        @note: If you're only interested in a specific breakpoint type, or in
            breakpoints for a specific process or thread, it's probably faster
            to call one of the following methods:
             - L{get_all_code_breakpoints}
             - L{get_all_page_breakpoints}
             - L{get_all_hardware_breakpoints}
             - L{get_process_code_breakpoints}
             - L{get_process_page_breakpoints}
             - L{get_process_hardware_breakpoints}
             - L{get_thread_hardware_breakpoints}

        @rtype:  list of tuple( pid, tid, bp )
        @return: List of all breakpoints.
        """
        bplist = list()

        # Get the code breakpoints.
        for (pid, bp) in self.get_all_code_breakpoints():
            bplist.append( (pid, None, bp) )

        # Get the page breakpoints.
        for (pid, bp) in self.get_all_page_breakpoints():
            bplist.append( (pid, None, bp) )

        # Get the hardware breakpoints.
        for (tid, bp) in self.get_all_hardware_breakpoints():
            pid = self.system.get_thread(tid).get_pid()
            bplist.append( (pid, tid, bp) )

        # Return the list of breakpoints.
        return bplist

    def get_all_code_breakpoints(self):
        """
        @rtype:  list of tuple( int, L{CodeBreakpoint} )
        @return: All code breakpoints as a list of tuples (pid, bp).
        """
        return [ (pid, bp) for ((pid, address), bp) in self.__codeBP.iteritems() ]

    def get_all_page_breakpoints(self):
        """
        @rtype:  list of tuple( int, L{PageBreakpoint} )
        @return: All page breakpoints as a list of tuples (pid, bp).
        """
##        return list( set( [ (pid, bp) for ((pid, address), bp) in self.__pageBP.itervalues() ] ) )
        result = set()
        for ((pid, address), bp) in self.__pageBP.itervalues():
            result.add( (pid, bp) )
        return list(result)

    def get_all_hardware_breakpoints(self):
        """
        @rtype:  list of tuple( int, L{HardwareBreakpoint} )
        @return: All hardware breakpoints as a list of tuples (tid, bp).
        """
        result = list()
        for (tid, bplist) in self.__hardwareBP.iteritems():
            for bp in bplist:
                result.append( (tid, bp) )
        return result

    def get_process_breakpoints(self, dwProcessId):
        """
        Returns all breakpoint objects for the given process as a list of tuples.

        Each tuple contains:
         - Process global ID to which the breakpoint applies.
         - Thread global ID to which the breakpoint applies, or C{None}.
         - The L{Breakpoint} object itself.

        @note: If you're only interested in a specific breakpoint type, or in
            breakpoints for a specific process or thread, it's probably faster
            to call one of the following methods:
             - L{get_all_code_breakpoints}
             - L{get_all_page_breakpoints}
             - L{get_all_hardware_breakpoints}
             - L{get_process_code_breakpoints}
             - L{get_process_page_breakpoints}
             - L{get_process_hardware_breakpoints}
             - L{get_thread_hardware_breakpoints}

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @rtype:  list of tuple( pid, tid, bp )
        @return: List of all breakpoints for the given process.
        """
        bplist = list()

        # Get the code breakpoints.
        for bp in self.get_process_code_breakpoints(dwProcessId):
            bplist.append( (dwProcessId, None, bp) )

        # Get the page breakpoints.
        for bp in self.get_process_page_breakpoints(dwProcessId):
            bplist.append( (dwProcessId, None, bp) )

        # Get the hardware breakpoints.
        for (tid, bp) in self.get_process_hardware_breakpoints(dwProcessId):
            pid = self.system.get_thread(tid).get_pid()
            bplist.append( (dwProcessId, tid, bp) )

        # Return the list of breakpoints.
        return bplist

    def get_process_code_breakpoints(self, dwProcessId):
        """
        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @rtype:  list of L{CodeBreakpoint}
        @return: All code breakpoints for the given process.
        """
        result = list()
        for ((pid, address), bp) in self.__codeBP.iteritems():
            if pid == dwProcessId:
                result.append(bp)
        return result

    def get_process_page_breakpoints(self, dwProcessId):
        """
        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @rtype:  list of L{PageBreakpoint}
        @return: All page breakpoints for the given process.
        """
        result = list()
        for ((pid, address), bp) in self.__pageBP.itervalues():
            if pid == dwProcessId:
                result.append(bp)
        return result

    def get_thread_hardware_breakpoints(self, dwThreadId):
        """
        @see: L{get_process_hardware_breakpoints}

        @type  dwThreadId: int
        @param dwThreadId: Thread global ID.

        @rtype:  list of L{HardwareBreakpoint}
        @return: All hardware breakpoints for the given thread.
        """
        result = list()
        for (tid, bplist) in self.__hardwareBP.iteritems():
            if tid == dwThreadId:
                for bp in bplist:
                    result.append(bp)
        return result

    def get_process_hardware_breakpoints(self, dwProcessId):
        """
        @see: L{get_thread_hardware_breakpoints}

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.

        @rtype:  list of tuple( int, L{HardwareBreakpoint} )
        @return: All hardware breakpoints for each thread in the given process
            as a list of tuples (tid, bp).
        """
        result = list()
        aProcess = self.system.get_process(dwProcessId)
        for dwThreadId in aProcess.iter_thread_ids():
            if dwThreadId in self.__hardwareBP:
                bplist = self.__hardwareBP[dwThreadId]
                for bp in bplist:
                    result.append( (dwThreadId, bp) )
        return result

#------------------------------------------------------------------------------

    def enable_all_breakpoints(self):
        """
        Enables all disabled breakpoints in all processes.

        @see:
            enable_code_breakpoint,
            enable_page_breakpoint,
            enable_hardware_breakpoint
        """

        # disable code breakpoints
        for (pid, bp) in self.get_all_code_breakpoints():
            if bp.is_disabled():
                self.enable_code_breakpoint(pid, bp.get_address())

        # disable page breakpoints
        for (pid, bp) in self.get_all_page_breakpoints():
            if bp.is_disabled():
                self.enable_page_breakpoint(pid, bp.get_address())

        # disable hardware breakpoints
        for (tid, bp) in self.get_all_hardware_breakpoints():
            if bp.is_disabled():
                self.enable_hardware_breakpoint(tid, bp.get_address())

    def enable_one_shot_all_breakpoints(self):
        """
        Enables for one shot all disabled breakpoints in all processes.

        @see:
            enable_one_shot_code_breakpoint,
            enable_one_shot_page_breakpoint,
            enable_one_shot_hardware_breakpoint
        """

        # disable code breakpoints for one shot
        for (pid, bp) in self.get_all_code_breakpoints():
            if bp.is_disabled():
                self.enable_one_shot_code_breakpoint(pid, bp.get_address())

        # disable page breakpoints for one shot
        for (pid, bp) in self.get_all_page_breakpoints():
            if bp.is_disabled():
                self.enable_one_shot_page_breakpoint(pid, bp.get_address())

        # disable hardware breakpoints for one shot
        for (tid, bp) in self.get_all_hardware_breakpoints():
            if bp.is_disabled():
                self.enable_one_shot_hardware_breakpoint(tid, bp.get_address())

    def disable_all_breakpoints(self):
        """
        Disables all breakpoints in all processes.

        @see:
            disable_code_breakpoint,
            disable_page_breakpoint,
            disable_hardware_breakpoint
        """

        # disable code breakpoints
        for (pid, bp) in self.get_all_code_breakpoints():
            self.disable_code_breakpoint(pid, bp.get_address())

        # disable page breakpoints
        for (pid, bp) in self.get_all_page_breakpoints():
            self.disable_page_breakpoint(pid, bp.get_address())

        # disable hardware breakpoints
        for (tid, bp) in self.get_all_hardware_breakpoints():
            self.disable_hardware_breakpoint(tid, bp.get_address())

    def erase_all_breakpoints(self):
        """
        Erases all breakpoints in all processes.

        @see:
            erase_code_breakpoint,
            erase_page_breakpoint,
            erase_hardware_breakpoint
        """

        # XXX HACK
        # With this trick we get to do it faster,
        # but I'm leaving the "nice" version commented out below,
        # just in case something breaks because of this.
        self.disable_all_breakpoints()
        self.__codeBP       = dict()
        self.__pageBP       = dict()
        self.__hardwareBP   = dict()
        self.__runningBP    = dict()

##        # erase code breakpoints
##        for (pid, bp) in self.get_all_code_breakpoints():
##            self.erase_code_breakpoint(pid, bp.get_address())
##
##        # erase page breakpoints
##        for (pid, bp) in self.get_all_page_breakpoints():
##            self.erase_page_breakpoint(pid, bp.get_address())
##
##        # erase hardware breakpoints
##        for (tid, bp) in self.get_all_hardware_breakpoints():
##            self.erase_hardware_breakpoint(tid, bp.get_address())

#------------------------------------------------------------------------------

    def enable_process_breakpoints(self, dwProcessId):
        """
        Enables all disabled breakpoints for the given process.

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.
        """

        # enable code breakpoints
        for bp in self.get_process_code_breakpoints(dwProcessId):
            if bp.is_disabled():
                self.enable_code_breakpoint(dwProcessId, bp.get_address())

        # enable page breakpoints
        for bp in self.get_process_page_breakpoints(dwProcessId):
            if bp.is_disabled():
                self.enable_page_breakpoint(dwProcessId, bp.get_address())

        # enable hardware breakpoints
        if self.system.has_process(dwProcessId):
            aProcess = self.system.get_process(dwProcessId)
        else:
            aProcess = Process(dwProcessId)
            aProcess.scan_threads()
        for aThread in aProcess.iter_threads():
            dwThreadId = aThread.get_tid()
            for bp in self.get_thread_hardware_breakpoints(dwThreadId):
                if bp.is_disabled():
                    self.enable_hardware_breakpoint(dwThreadId, bp.get_address())

    def enable_one_shot_process_breakpoints(self, dwProcessId):
        """
        Enables for one shot all disabled breakpoints for the given process.

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.
        """

        # enable code breakpoints for one shot
        for bp in self.get_process_code_breakpoints(dwProcessId):
            if bp.is_disabled():
                self.enable_one_shot_code_breakpoint(dwProcessId, bp.get_address())

        # enable page breakpoints for one shot
        for bp in self.get_process_page_breakpoints(dwProcessId):
            if bp.is_disabled():
                self.enable_one_shot_page_breakpoint(dwProcessId, bp.get_address())

        # enable hardware breakpoints for one shot
        if self.system.has_process(dwProcessId):
            aProcess = self.system.get_process(dwProcessId)
        else:
            aProcess = Process(dwProcessId)
            aProcess.scan_threads()
        for aThread in aProcess.iter_threads():
            dwThreadId = aThread.get_tid()
            for bp in self.get_thread_hardware_breakpoints(dwThreadId):
                if bp.is_disabled():
                    self.enable_one_shot_hardware_breakpoint(dwThreadId, bp.get_address())

    def disable_process_breakpoints(self, dwProcessId):
        """
        Disables all breakpoints for the given process.

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.
        """

        # disable code breakpoints
        for bp in self.get_process_code_breakpoints(dwProcessId):
            self.disable_code_breakpoint(dwProcessId, bp.get_address())

        # disable page breakpoints
        for bp in self.get_process_page_breakpoints(dwProcessId):
            self.disable_page_breakpoint(dwProcessId, bp.get_address())

        # disable hardware breakpoints
        if self.system.has_process(dwProcessId):
            aProcess = self.system.get_process(dwProcessId)
        else:
            aProcess = Process(dwProcessId)
            aProcess.scan_threads()
        for aThread in aProcess.iter_threads():
            dwThreadId = aThread.get_tid()
            for bp in self.get_thread_hardware_breakpoints(dwThreadId):
                self.disable_hardware_breakpoint(dwThreadId, bp.get_address())

    def erase_process_breakpoints(self, dwProcessId):
        """
        Erases all breakpoints for the given process.

        @type  dwProcessId: int
        @param dwProcessId: Process global ID.
        """

        # disable breakpoints first
        # if an error occurs, no breakpoint is erased
        self.disable_breakpoints_for_process(dwProcessId)

        # erase code breakpoints
        for bp in self.get_process_code_breakpoints(dwProcessId):
            self.erase_code_breakpoint(dwProcessId, bp.get_address())

        # erase page breakpoints
        for bp in self.get_process_page_breakpoints(dwProcessId):
            self.erase_page_breakpoint(dwProcessId, bp.get_address())

        # erase hardware breakpoints
        if self.system.has_process(dwProcessId):
            aProcess = self.system.get_process(dwProcessId)
        else:
            aProcess = Process(dwProcessId)
            aProcess.scan_threads()
        for aThread in aProcess.iter_threads():
            dwThreadId = aThread.get_tid()
            for bp in self.get_thread_hardware_breakpoints(dwThreadId):
                self.erase_hardware_breakpoint(dwThreadId, bp.get_address())

#------------------------------------------------------------------------------

    def notify_guard_page(self, event):
        """
        Notify breakpoints of a guard page exception event.

        @type  event: L{ExceptionEvent}
        @param event: Guard page exception event.

        @rtype:  bool
        @return: C{True} to call the user-defined handle, C{False} otherwise.
        """
        address         = event.get_fault_address()
        pid             = event.get_pid()
        bCallHandler    = True

        # Align address to page boundary
        address = address & 0xFFFFF000

        # Do we have a page breakpoint there?
        key = (pid, address)
        if key in self.__pageBP:
            bp = self.__pageBP[key]

            # Breakpoint is ours.
            event.continueStatus = win32.DBG_EXCEPTION_HANDLED

            # Set the "breakpoint" property of the event object.
            event.breakpoint     = bp

            # Ignore disabled and running breakpoints.
            # (This should not happen anyway)
            if bp.is_enabled() or bp.is_one_shot():

                # Hit the breakpoint.
                bp.hit(event)

                # Remember breakpoints in RUNNING state.
                if bp.is_running():
                    tid = event.get_tid()
                    self.__add_running_bp(tid, bp)

                # Evaluate the breakpoint condition.
                bCondition = bp.eval_condition(event)

                # If the breakpoint is automatic, run the action.
                # If not, notify the user.
                if bCondition and bp.is_automatic():
                    bp.run_action(event)
                    bCallHandler = False
                else:
                    bCallHandler = bCondition

        return bCallHandler

    def notify_breakpoint(self, event):
        """
        Notify breakpoints of a breakpoint exception event.

        @type  event: L{ExceptionEvent}
        @param event: Breakpoint exception event.

        @rtype:  bool
        @return: C{True} to call the user-defined handle, C{False} otherwise.
        """
        address         = event.get_exception_address()
        pid             = event.get_pid()
        bCallHandler    = True

        # Do we have a code breakpoint there?
        key = (pid, address)
        if key in self.__codeBP:
            bp = self.__codeBP[key]

            # Breakpoint is ours.
            event.continueStatus = win32.DBG_EXCEPTION_HANDLED

            # Set the "breakpoint" property of the event object.
            event.breakpoint     = bp

            # Ignore disabled breakpoints.
            if not bp.is_disabled():

                # Hit the breakpoint.
                bp.hit(event)

                # Change the EIP to the exception address.
                # This accounts for the change in EIP caused by
                # executing the breakpoint instruction, no matter
                # the size of it.
                aThread = event.get_thread()
                aThread.set_pc(address)

                # Remember breakpoints in RUNNING state.
                if bp.is_running():
                    tid = event.get_tid()
                    self.__add_running_bp(tid, bp)

                # Evaluate the breakpoint condition.
                bCondition = bp.eval_condition(event)

                # If the breakpoint is automatic, run the action.
                # If not, notify the user.
                if bCondition and bp.is_automatic():
                    bCallHandler = bp.run_action(event)
                else:
                    bCallHandler = bCondition

        # Handle the system breakpoint.
        elif event.get_process().is_system_defined_breakpoint(address):
            event.continueStatus = win32.DBG_EXCEPTION_HANDLED

        return bCallHandler

    def notify_single_step(self, event):
        """
        Notify breakpoints of a single step exception event.

        @type  event: L{ExceptionEvent}
        @param event: Single step exception event.

        @rtype:  bool
        @return: C{True} to call the user-defined handle, C{False} otherwise.
        """
        pid             = event.get_pid()
        tid             = event.get_tid()
        bCallHandler    = True

        # When the thread is in tracing mode,
        # don't pass the exception to the debugee
        # and set the trap flag again.
        if self.is_tracing(tid):
            event.continueStatus = win32.DBG_EXCEPTION_HANDLED
            event.get_thread().set_tf()

        # Handle breakpoints in RUNNING state.
        while self.__has_running_bp(tid):
            event.continueStatus = win32.DBG_EXCEPTION_HANDLED
            bCallHandler = False
            bp = self.__pop_running_bp(tid)
            bp.hit(event)

        # Handle hardware breakpoints.
        if tid in self.__hardwareBP:
            aThread = event.get_thread()
            ctx     = aThread.get_context(win32.CONTEXT_DEBUG_REGISTERS)
            Dr6     = ctx['Dr6']
            ctx['Dr6'] = Dr6 & DebugRegister.clearHitMask
            aThread.set_context(ctx)
            bFoundBreakpoint = False
            bCondition       = False
            hwbpList = [ bp for bp in self.__hardwareBP[tid] ]
            for bp in hwbpList:
                if not bp in self.__hardwareBP[tid]:
                    continue    # it was removed by a user-defined callback
                slot = bp.get_slot()
                if (slot is not None) and (Dr6 & DebugRegister.hitMask[slot]):
                    if not bFoundBreakpoint:    # set before actions are called
                        event.continueStatus = win32.DBG_EXCEPTION_HANDLED
                    bFoundBreakpoint = True
                    event.breakpoint = bp
                    bp.hit(event)
                    if bp.is_running():
                        self.__add_running_bp(tid, bp)
                    bThisCondition = bp.eval_condition(event)
                    if bThisCondition and bp.is_automatic():
                        bp.run_action(event)
                        bThisCondition = False
                    bCondition = bCondition or bThisCondition
            if bFoundBreakpoint:
                bCallHandler = bCondition

        # Always call the user-defined handler
        # when the thread is in tracing mode.
        if self.is_tracing(tid):
            bCallHandler = True

        return bCallHandler

    def notify_exit_thread(self, event):
        """
        Notify the termination of a thread.

        @type  event: L{ExitThreadEvent}
        @param event: Exit thread event.

        @rtype:  bool
        @return: C{True} to call the user-defined handle, C{False} otherwise.
        """
        self.__cleanup_thread(event)
        return True

    def notify_exit_process(self, event):
        """
        Notify the termination of a process.

        @type  event: L{ExitProcessEvent}
        @param event: Exit process event.

        @rtype:  bool
        @return: C{True} to call the user-defined handle, C{False} otherwise.
        """
        self.__cleanup_process(event)
        self.__cleanup_thread(event)
        return True

    def notify_unload_dll(self, event):
        """
        Notify the unloading of a DLL.

        @type  event: L{UnloadDLLEvent}
        @param event: Unload DLL event.

        @rtype:  bool
        @return: C{True} to call the user-defined handle, C{False} otherwise.
        """
        self.__cleanup_module(event)
        return True

#------------------------------------------------------------------------------

    def __set_break(self, pid, address, action):
        """
        Used by L{break_at} and L{stalk_at}.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of code instruction to break at.

        @type  action: function
        @param action: (Optional) Action callback function.

            See L{define_code_breakpoint} for more details.
        """
        if self.has_code_breakpoint(pid, address):
            bp = self.get_code_breakpoint(pid, address)
            if bp.get_action() != action:
                bp.set_action(action)
        else:
            self.define_code_breakpoint(pid, address, True, action)
            bp = self.get_code_breakpoint(pid, address)
        return bp

    def __clear_break(self, pid, address):
        """
        Used by L{dont_break_at} and L{dont_stalk_at}.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of code breakpoint.
        """
        if self.has_code_breakpoint(pid, address):
            self.erase_code_breakpoint(pid, address)

    def stalk_at(self, pid, address, action = None):
        """
        Sets a one shot code breakpoint at the given process and address.

        @see: L{break_at}, L{dont_stalk_at}

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of code instruction to break at.

        @type  action: function
        @param action: (Optional) Action callback function.

            See L{define_code_breakpoint} for more details.
        """
        bp = self.__set_break(pid, address, action)
        if not bp.is_one_shot():
            self.enable_one_shot_code_breakpoint(pid, address)

    def break_at(self, pid, address, action = None):
        """
        Sets a code breakpoint at the given process and address.

        @see: L{stalk_at}, L{dont_break_at}

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of code instruction to break at.

        @type  action: function
        @param action: (Optional) Action callback function.

            See L{define_code_breakpoint} for more details.
        """
        bp = self.__set_break(pid, address, action)
        if not bp.is_enabled():
            self.enable_code_breakpoint(pid, address)

    def dont_break_at(self, pid, address):
        """
        Clears a code breakpoint set by L{break_at}.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of code instruction to break at.
        """
        self.__clear_break(pid, address)

    def dont_stalk_at(self, pid, address):
        """
        Clears a code breakpoint set by L{stalk_at}.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of code instruction to break at.
        """
        self.__clear_break(pid, address)

#------------------------------------------------------------------------------

    def hook_function(self, pid, address,          preCB = None, postCB = None,
                                                               paramCount = 0):
        """
        Sets a function hook at the given address.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Function address.

        @type  preCB: function
        @param preCB: (Optional) Callback triggered on function entry.

            The signature for the callback can be something like this::

                def pre_LoadLibraryEx(event, *params):
                    ra   = params[0]        # return address
                    argv = params[1:]       # function parameters

                    # (...)

            But if you passed the right number of arguments, you can also
            use a signature like this::

                def pre_LoadLibraryEx(event, ra, lpFilename, hFile, dwFlags):
                    szFilename = event.get_process().peek_string(lpFilename)

                    # (...)

            In the above example, the value for C{paramCount} would be C{3}.

        @type  postCB: function
        @param postCB: (Optional) Callback triggered on function exit.

            The signature for the callback would be something like this::

                def post_LoadLibraryEx(event, return_value):

                    # (...)

        @type  paramCount: int
        @param paramCount:
            (Optional) Number of parameters for the C{preCB} callback,
            not counting the return address. Parameters are read from
            the stack and assumed to be DWORDs.
        """
        # XXX HACK
        # This will be removed when hooks are supported in AMD64.
        if System.arch != 'i386':
            raise NotImplementedError

        hookObj = Hook(preCB, postCB, paramCount)
        self.break_at(pid, address, hookObj)

    def stalk_function(self, pid, address,         preCB = None, postCB = None,
                                                               paramCount = 0):
        """
        Sets a one-shot function hook at the given address.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Function address.

        @type  preCB: function
        @param preCB: (Optional) Callback triggered on function entry.

            The signature for the callback can be something like this::

                def pre_LoadLibraryEx(event, *params):
                    ra   = params[0]        # return address
                    argv = params[1:]       # function parameters

                    # (...)

            But if you passed the right number of arguments, you can also
            use a signature like this::

                def pre_LoadLibraryEx(event, ra, lpFilename, hFile, dwFlags):
                    szFilename = event.get_process().peek_string(lpFilename)

                    # (...)

            In the above example, the value for C{paramCount} would be C{3}.

        @type  postCB: function
        @param postCB: (Optional) Callback triggered on function exit.

            The signature for the callback would be something like this::

                def post_LoadLibraryEx(event, return_value):

                    # (...)

        @type  paramCount: int
        @param paramCount:
            (Optional) Number of parameters for the C{preCB} callback,
            not counting the return address. Parameters are read from
            the stack and assumed to be DWORDs.
        """
        # XXX HACK
        # This will be removed when hooks are supported in AMD64.
        if System.arch != 'i386':
            raise NotImplementedError

        hookObj = Hook(preCB, postCB, paramCount)
        self.stalk_at(pid, address, hookObj)

    def dont_hook_function(self, pid, address):
        """
        Removes a function hook set by L{hook_function}.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Function address.
        """
        self.dont_break_at(pid, address)

    # alias
    unhook_function = dont_hook_function

    def dont_stalk_function(self, pid, address):
        """
        Removes a function hook set by L{stalk_function}.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Function address.
        """
        self.dont_stalk_at(pid, address)

#------------------------------------------------------------------------------

    def __set_variable_watch(self, tid, address, size, action):
        """
        Used by L{watch_variable} and L{stalk_variable}.

        @type  tid: int
        @param tid: Thread global ID.

        @type  address: int
        @param address: Memory address of variable to watch.

        @type  size: int
        @param size: Size of variable to watch. The only supported sizes are:
            byte (1), word (2), dword (4) and qword (8).

        @type  action: function
        @param action: (Optional) Action callback function.

            See L{define_hardware_breakpoint} for more details.

        @rtype:  L{HardwareBreakpoint}
        @return: Hardware breakpoint at the requested address.
        """

        # TODO
        # Maybe we could merge the breakpoints instead of overwriting them.

        if size == 1:
            sizeFlag = self.BP_WATCH_BYTE
        elif size == 2:
            sizeFlag = self.BP_WATCH_WORD
        elif size == 4:
            sizeFlag = self.BP_WATCH_DWORD
        elif size == 8:
            sizeFlag = self.BP_WATCH_QWORD
        else:
            raise ValueError, "Bad size for variable watch: %r" % size
        if self.has_hardware_breakpoint(tid, address):
            bp = self.get_hardware_breakpoint(tid, address)
            if  bp.get_trigger() != self.BP_BREAK_ON_ACCESS or \
                bp.get_watch()   != sizeFlag:
                    self.erase_hardware_breakpoint(tid, address)
                    self.define_hardware_breakpoint(tid, address,
                               self.BP_BREAK_ON_ACCESS, sizeFlag, True, action)
                    bp = self.get_hardware_breakpoint(tid, address)
        else:
            self.define_hardware_breakpoint(tid, address,
                               self.BP_BREAK_ON_ACCESS, sizeFlag, True, action)
            bp = self.get_hardware_breakpoint(tid, address)
        return bp

    def __clear_variable_watch(self, tid, address):
        """
        Used by L{dont_watch_variable} and L{dont_stalk_variable}.

        @type  tid: int
        @param tid: Thread global ID.

        @type  address: int
        @param address: Memory address of variable to stop watching.
        """
        if self.has_hardware_breakpoint(tid, address):
            self.erase_hardware_breakpoint(tid, address)

    def watch_variable(self, tid, address, size, action = None):
        """
        Sets a hardware breakpoint at the given thread, address and size.

        @see: L{dont_watch_variable}

        @type  tid: int
        @param tid: Thread global ID.

        @type  address: int
        @param address: Memory address of variable to watch.

        @type  size: int
        @param size: Size of variable to watch. The only supported sizes are:
            byte (1), word (2), dword (4) and qword (8).

        @type  action: function
        @param action: (Optional) Action callback function.

            See L{define_hardware_breakpoint} for more details.
        """
        bp = self.__set_variable_watch(tid, address, size, action)
        if not bp.is_enabled():
            self.enable_hardware_breakpoint(tid, address)

    def stalk_variable(self, tid, address, size, action = None):
        """
        Sets a one-shot hardware breakpoint at the given thread,
        address and size.

        @see: L{dont_watch_variable}

        @type  tid: int
        @param tid: Thread global ID.

        @type  address: int
        @param address: Memory address of variable to watch.

        @type  size: int
        @param size: Size of variable to watch. The only supported sizes are:
            byte (1), word (2), dword (4) and qword (8).

        @type  action: function
        @param action: (Optional) Action callback function.

            See L{define_hardware_breakpoint} for more details.
        """
        bp = self.__set_variable_watch(tid, address, size, action)
        if not bp.is_one_shot():
            self.enable_one_shot_hardware_breakpoint(tid, address)

    def dont_watch_variable(self, tid, address):
        """
        Clears a hardware breakpoint set by L{watch_variable}.

        @type  tid: int
        @param tid: Thread global ID.

        @type  address: int
        @param address: Memory address of variable to stop watching.
        """
        self.__clear_variable_watch(tid, address)

    def dont_stalk_variable(self, tid, address):
        """
        Clears a hardware breakpoint set by L{stalk_variable}.

        @type  tid: int
        @param tid: Thread global ID.

        @type  address: int
        @param address: Memory address of variable to stop watching.
        """
        self.__clear_variable_watch(tid, address)

#------------------------------------------------------------------------------

    def __set_buffer_watch(self, pid, address, size, action, bOneShot):
        """
        Used by L{watch_buffer} and L{stalk_buffer}.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of buffer to watch.

        @type  size: int
        @param size: Size in bytes of buffer to watch.

        @type  action: function
        @param action: (Optional) Action callback function.

            See L{define_page_breakpoint} for more details.

        @type  bOneShot: bool
        @param bOneShot:
            C{True} to set a one-shot breakpoint,
            C{False} to set a normal breakpoint.
        """

        # TODO
        # Check for overlapping page breakpoints.

        # Check the size isn't zero or negative.
        if size < 1:
            raise ValueError, "Bad size for buffer watch: %r" % size

        # Get the process object.
        aProcess = self.system.get_process(pid)

        # Get the base address and size in pages required for this buffer.
        base  = MemoryAddresses.align_address_to_page_start(address)
        limit = MemoryAddresses.align_address_to_page_end(address + size)
        pages = MemoryAddresses.get_buffer_size_in_pages(address, size)

        try:

            # For each page:
            #  + if a page breakpoint exists reuse it
            #  + if it doesn't exist define it

            bset = set()     # all breakpoints used
            nset = set()     # newly defined breakpoints
            cset = set()     # condition objects
            for page_addr in xrange(base, limit, System.pageSize):

                # If a breakpoints exists, reuse it.
                if self.has_page_breakpoint(pid, page_addr):
                    bp = self.get_page_breakpoint(pid, page_addr)
                    if bp not in bset:
                        condition = bp.get_condition()
                        if not condition in cset:
                            if not isinstance(condition, BufferWatch):
                                # this shouldn't happen unless you tinkered with it
                                # or defined your own page breakpoints manually.
                                msg = "Can't watch buffer at page %s"
                                msg = msg % HexDump.address(page_addr)
                                raise RuntimeError, msg
                            cset.add(condition)
                        bset.add(bp)

                # If it doesn't, define it.
                else:
                    condition = BufferWatch()
                    bp = self.define_page_breakpoint(pid, page_addr, 1,
                                                     condition = condition)
                    bset.add(bp)
                    nset.add(bp)
                    cset.add(condition)

            # For each breakpoint, enable it if needed.
            if bOneShot:
                for bp in bset:
                    if not bp.is_one_shot():
                        bp.one_shot(aProcess, None)
            else:
                for bp in bset:
                    if not bp.is_enabled():
                        bp.enable(aProcess, None)

        # On error...
        except:

            # Erase the newly defined breakpoints.
            for bp in nset:
                try:
                    self.erase_page_breakpoint(pid, bp.get_address())
                except:
                    pass

            # Pass the exception to the caller
            raise

        # For each condition object, add the new buffer.
        for condition in cset:
            condition.add(address, size, action)

    def __clear_buffer_watch(self, pid, address, size):
        """
        Used by L{dont_watch_buffer} and L{dont_stalk_buffer}.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of buffer to stop watching.

        @type  size: int
        @param size: Size in bytes of buffer to stop watching.
        """

        # Check the size isn't zero or negative.
        if size < 1:
            raise ValueError, "Bad size for buffer watch: %r" % size

        # Get the base address and size in pages required for this buffer.
        base  = MemoryAddresses.align_address_to_page_start(address)
        limit = MemoryAddresses.align_address_to_page_end(address + size)
        pages = MemoryAddresses.get_buffer_size_in_pages(address, size)

        # For each page, get the breakpoint and it's condition object.
        # For each condition, remove the buffer.
        # For each breakpoint, if no buffers are on watch, erase it.
        cset = set()     # condition objects
        for page_addr in xrange(base, limit, System.pageSize):
            if self.has_page_breakpoint(pid, page_addr):
                bp = self.get_page_breakpoint(pid, page_addr)
                condition = bp.get_condition()
                if condition not in cset:
                    if not isinstance(condition, BufferWatch):
                        # this shouldn't happen unless you tinkered with it
                        # or defined your own page breakpoints manually.
                        continue
                    cset.add(condition)
                    if condition.exists(address, size):
                        condition.remove(address, size)
                    if condition.count() == 0:
                        try:
                            self.erase_page_breakpoint(pid, bp.get_address())
                        except WindowsError:
                            pass

    def watch_buffer(self, pid, address, size, action = None):
        """
        Sets a page breakpoint and notifies when the given buffer is accessed.

        @see: L{dont_watch_variable}

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of buffer to watch.

        @type  size: int
        @param size: Size in bytes of buffer to watch.

        @type  action: function
        @param action: (Optional) Action callback function.

            See L{define_page_breakpoint} for more details.
        """
        self.__set_buffer_watch(pid, address, size, action, False)

    def stalk_buffer(self, pid, address, size, action = None):
        """
        Sets a one-shot page breakpoint and notifies
        when the given buffer is accessed.

        @see: L{dont_watch_variable}

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of buffer to watch.

        @type  size: int
        @param size: Size in bytes of buffer to watch.

        @type  action: function
        @param action: (Optional) Action callback function.

            See L{define_page_breakpoint} for more details.
        """
        self.__set_buffer_watch(pid, address, size, action, True)

    def dont_watch_buffer(self, pid, address, size):
        """
        Clears a page breakpoint set by L{watch_buffer}.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of buffer to stop watching.

        @type  size: int
        @param size: Size in bytes of buffer to stop watching.
        """
        self.__clear_buffer_watch(pid, address, size)

    def dont_stalk_buffer(self, pid, address, size):
        """
        Clears a page breakpoint set by L{stalk_buffer}.

        @type  pid: int
        @param pid: Process global ID.

        @type  address: int
        @param address: Memory address of buffer to stop watching.

        @type  size: int
        @param size: Size in bytes of buffer to stop watching.
        """
        self.__clear_buffer_watch(pid, address, size)

#------------------------------------------------------------------------------

# XXX TODO
# Add "action" parameter to tracing mode

    def __start_tracing(self, thread):
        """
        @type  thread: L{Thread}
        @param thread: Thread to start tracing.
        """
        tid = thread.get_tid()
        if not tid in self.__tracing:
            thread.set_tf()
            self.__tracing.add(tid)

    def __stop_tracing(self, thread):
        """
        @type  thread: L{Thread}
        @param thread: Thread to stop tracing.
        """
        tid = thread.get_tid()
        if tid in self.__tracing:
            self.__tracing.remove(tid)
            thread.clear_tf()

    def is_tracing(self, tid):
        """
        @type  tid: int
        @param tid: Thread global ID.

        @rtype:  bool
        @return: C{True} if the thread is being traced, C{False} otherwise.
        """
        return tid in self.__tracing

    def get_traced_tids(self):
        """
        Retrieves the list of global IDs of all threads being traced.

        @rtype:  list( int... )
        @return: List of thread global IDs.
        """
        tids = list(self.__tracing)
        tids.sort()
        return tids

    def start_tracing(self, tid):
        """
        Start tracing mode in the given thread.

        @type  tid: int
        @param tid: Global ID of thread to start tracing.
        """
        if not self.is_tracing(tid):
            thread = self.system.get_thread(tid)
            self.__start_tracing(thread)

    def stop_tracing(self, tid):
        """
        Stop tracing mode in the given thread.

        @type  tid: int
        @param tid: Global ID of thread to stop tracing.
        """
        if self.is_tracing(tid):
            thread = self.system.get_thread(tid)
            self.__stop_tracing(thread)

    def start_tracing_process(self, pid):
        """
        Start tracing mode for all threads in the given process.

        @type  pid: int
        @param pid: Global ID of process to start tracing.
        """
        for thread in self.system.get_process(pid).iter_threads():
            self.__start_tracing(thread)

    def stop_tracing_process(self, pid):
        """
        Stop tracing mode for all threads in the given process.

        @type  pid: int
        @param pid: Global ID of process to stop tracing.
        """
        for thread in self.system.get_process(pid).iter_threads():
            self.__stop_tracing(thread)

    def start_tracing_all(self):
        """
        Start tracing mode for all threads in all debugees.
        """
        for pid in self.get_debugee_pids():
            self.start_tracing_process(pid)

    def stop_tracing_all(self):
        """
        Stop tracing mode for all threads in all debugees.
        """
        for pid in self.get_debugee_pids():
            self.stop_tracing_process(pid)

#------------------------------------------------------------------------------

    def resolve_exported_function(self, pid, modName, procName):
        """
        Resolves the exported DLL function for the given process.

        @type  pid: int
        @param pid: Process global ID.

        @type  modName: str
        @param modName: Name of the module that exports the function.

        @type  procName: str
        @param procName: Name of the exported function to resolve.

        @rtype:  int, None
        @return: On success, the address of the exported function.
            On failure, returns C{None}.
        """
        aProcess = self.system.get_process(pid)
        aModule = aProcess.get_module_by_name(modName)
        if not aModule:
            aProcess.scan_modules()
            aModule = aProcess.get_module_by_name(modName)
        if aModule:
            address = aModule.resolve(procName)
            return address
        return None

    def resolve_label(self, pid, label):
        """
        Resolves a label for the given process.

        @type  pid: int
        @param pid: Process global ID.

        @type  label: str
        @param label: Label to resolve.

        @rtype:  int
        @return: Memory address pointed to by the label.

        @raise ValueError: The label is malformed or impossible to resolve.
        @raise RuntimeError: Cannot resolve the module or function.
        """
        return self.get_process(pid).resolve_label(label)
