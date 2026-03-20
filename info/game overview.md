# Pi
Pi a game revolving around hacking, exploration, graphical text adventures and self reflection

## Origin and Spirit

This project began as a conversation about the ZX Spectrum, Elite, Tau Ceti, and a babysitting job lost to a glowing screen. It became something considerably larger. What follows is the complete record of every conclusion drawn, every design decision made, every dream articulated.

The guiding philosophy throughout: constraints are chosen, not imposed. We are not building real hardware. We are building a fiction that feels true — the simplicity of systems you could hold completely in one head, understand from the bottom up, modify without fear because you knew what everything did.

---

## The 46 Terminal and the 56 Mainframe

The game world is built around two machines. The player sits at a **46 terminal** — the T46, the interface, the thing the player uses. They connect to a **M56 mainframe**. The mainframe is a virtual fantasy computer with a defined CPU, assembly language, memory model. The game explores a computer game universe that runs in a text adventure which in turn runs on virtual hardware. The user first navigates the text adventure world, then as he finds out that the M56 is hackable he starts to interact with the simplified os, its cpu, its assembly language, its text adventure interpreter Zero and its inbuilt computer language Pi.

## The game world

The user finds himself in a strange world. He knows not how he got here or what is going on. All the world contains is a computer terminal. They boot up to a prompt and notice they can run a computer program that fires up a graphical text adventure game. Achieving goals in the game has implications to the computer system they are interacting with. new files become available or new apis or devices. At the moment the story is not progressed much more, than that the user progressess through a world of tiers, a completely automated world, its inhabitants long dead, the world continues to exist due to its automated self repairing computer systems. Essentially the user finds themselves in a layered system of escape rooms. As they progress, they, similarly to talos principle, find themselves confronted with the question of who they are, what life is, what meaning is, as the world of the game and the world of the computer start to weave into one another.

The game is also about teaching real computer technology, learning to hack a system, understand the os, the built in computer language, the interpreter the text adventure engine and how they combine to build a working computer.

## The Fantasy Hardware

Only the M56 is hackable. It is a working but extremely simplified virtual computer with a virtual cpu, a simple but working os, system calls, assembler, disassembler, pi interpreter and text adventure interpreter. All these systems the language and the text adventure interpreter are implemented in M56

M56

CPU:      Custom 8-bit (see CPU Architecture below)
RAM:      probably 64KB user + 24KB system
ROM:      OS, assembler, disassember, pi interpreter, text adventure interpreter

Storage:  Utronic Data Cartridge
Sound:    Single channel beeper
Ports:    Serial, parallel, expansion bus

UTRONIC 2+ ADDITIONS:
RAM:      +64KB graphics bank
Display:  +256×192 pixel mode, Spectrum attribute colour system
Sound:    +3 channel synthesis (AY equivalent)

T46

The T46 is not virtual hardware. It acts like a graphical terminal that can receive text and graphics commands and send text input.
The user interacts with the mainframe via a shell that is running on the terminal.
Display:  80×25 text, 256 colours indexed to the Doom colour palette

---

### CPU Architecture

The architecture is super simplified. No interrupts, no os, no device drivers. We just have streams that can be written to

**Design philosophy:** The constraints are aesthetic and pedagogical, not technical. We keep the 8-bit register feel, simple instruction set, fixed instruction width, memory map with clear regions, privilege separation, vectored interrupts, and the Python-like language. We discard cycle-accurate emulation, real hardware timing, and actual memory constraints.

**Registers:**
```
8 × 16-bit general purpose registers: R0–R7
All registers are full accumulators — no bottleneck through a single accumulator
Four register banks (0–3)

Special registers:
PC  — 20-bit program counter
SP  — 20-bit stack pointer
FLAGS — zero, carry, overflow, negative, supervisor
CPG — code page register (4-bit)
DPG — data page register (4-bit)
```

**Registers in RAM (8051-style):**
Registers live at known addresses in the low system RAM. They are accessible by name in assembly or by direct memory address — they are the same thing. No separate register window. Debuggers have a unified view of everything.

8 multipurpose 16 bit registers R0 - R7. 

The complete CPU state is just memory:

0x00000             Reset entry point
                    Single Load immediate instruction
                    Jumps to OS init

0x00003 — 0x0003F   OS scratch / reserved (61 bytes)
                    Available for whatever the OS needs
                    Error codes, temporary storage
                    Early boot data

0x00040 — 0x000FF   CPU state and supervisor registers
                    R0-R7, FLAGS, CPG, DPG, SP, PC
                    All memory mapped as designed
0x040  
R0
R1
R2
R3
R4
R5
R6
R7
FLAGS
CPG ; Code page register lower nibble
DPG  ; Data page register higher nibble
SP 
PC


0x00100 — 0x003FF   Kernel call table
                    OS entry points
                    Syscall dispatch
                    The addresses user code can directly jump to.

0x00400 —           ROM
                    OS
                    Built-in functions
                    Pi interpreter
                    Zero interpreter

Above - user ram

**Fixed-width 24-bit instructions:**
```
23      19 18    16 15    13 12             0
┌─────────┬────────┬────────┬───────────────┐
│  opcode │   rs   │   rd   │  immediate    │
│  5 bits │ 3 bits │ 3 bits │   13 bits     │
└─────────┴────────┴────────┴───────────────┘

sr = source register (3 bits)
dr = destination register (3 bits = 8 register choices, R0–R7)
immediate = 13 bits = addresses 0x0000–0x1FFF
```

## 20-bit address space via page registers:
```
Physical address = page_register(4 bits) + 16-bit offset = 20 bits = 1MB
Three separate page registers: CPG (code), DPG (data)
A process can have 64KB code + 64KB data
```

**Privilege separation:**
No privileged modes as we only have a single thread, no cron no polling of 

## syscall tables
The 13-bit immediate field can only address 0x0000–0x1FFF. We use syscal vector tables to reach rom routines beyond this point.

#### opcode instruction set:
```
LOAD    src, dest     all addressing modes, mode in rs field

ADD     src, dest     src = register or imm13
SUB     src, dest     src = register or imm13
AND     src, dest     src = register or imm13
OR      src, dest     src = register or imm13
XOR     src, dest     src = register or imm13
NOT     dest

SFT     dest, #n      4-bit signed immediate, logical
SAR     dest, #n      4-bit positive immediate, arithmetic right
MUL     src, dest
DIV     src, dest
SWP     dest          exchange high and low bytes

JMP   cond, target    branch — never saves return address
CAL   cond, target    call — saves return address on stack
RET   cond            return — restores PC from stack
PUSH    src
POP     dest
NOP
```

#### Addressing modes:
```
LOAD  R0, R1              register to register
LOAD  [R0], R1            memory at address in R0, into R1
LOAD  R1, [R0]            R1 into memory at address in R0
LOAD  [R0+offset], R1     memory at R0+offset into R1
LOAD  R1, [R0+offset]     R1 into memory at R0+offset
LOAD  [PC+offset], R1     load from literal pool (the table idea)
```

#### Cal condition codes (3 bits = 8 conditions):
```
000  Z   — branch if zero
001  NZ  — branch if not zero
010  C   — branch if carry
011  NC  — branch if no carry
100  N   — branch if negative
101  NN  — branch if not negative
110  V   — branch if overflow
111  AL  — always (replaces a separate JMP opcode)
```
---

### Display System

The M56 has no graphics system. It sends ascii text and graphics commands to the terminal T46

The T46 graphics display resolution is 256 x 192 pixels. Each pixel is represented by a byte referring the DOOM colour palette.

Alternatively there is a text mode 80 by 25 lines, where we can implement a simple text editor. The user can also use the favourite text editor if they read and write a predetermined file.

**The colour palette:** The Doom palette. 256 entries chosen not for versatility but for mood — the colour of constructed places, functional things, old metal, things that have been wrong long enough to forget what right looked like. Organised in regions:


**Graphics style:** Hobbit-style vector graphics. Not stored as pixel data but as drawing commands — line, fill, arc. A scene is a program that draws itself. The world assembles visibly, line by line, fill spreading from seed points. The player watches the construction. 

---

## Part Two: The Software

### OS

We do not have an OS as we decided to strip away complexity like threads and interrupts. We just have system calls that read and write to devices. 

### Pi A simplified Python. Not full Python. The parts that are load-bearing for usability. Clean, warm, meeting the programmer where they naturally think.

```python
# Supported:
x = 42
name = "lyra"
flag = true

if condition:
    ...
elif condition:
    ...
else:
    ...

while condition:
    ...

for i in range(10):
    ...

def function(args):
    ...

items = [1, 2, 3]
items[0]

struct Character:
    name
    hp
    mp
```

#### Dropped from Python:
Classes (replaced by structs), exceptions (return codes), generators, closures, float arithmetic (integers only), imports (everything baked in).

#### The interpreter architecture:
A tree-walking interpreter. No bytecode VM needed — the machine is fast enough that interpreting the AST directly is fine. Three stages: lexer (~150 lines), parser (~300 lines), evaluator (~400 lines). Total language engine around 1000 lines.

#### The shell is the language.
Very simple shell commands for file system traversal, pi (python) repl to do more complicated commands.

## Built-in hardware functions (baked into ROM):
```python
# Display
pen(color)
plot(x, y)
line(x1, y1, x2, y2)
fill(x, y)          # flood fill from seed
rect(x, y, w, h)
arc(x, y, x1, y1, arc radius)
cls

# Input
key()                       # returns keycode or 0
joy()                       # returns joystick bitmask

# Storage
load(device id, "filename")            # returns when data ready
save(device id, "filename", data)

# terminal
send(terminal id, data) # to terminal
receive(terminal id, data) # from terminal


# Sound
no idea yet, possibly just a beep
```

```python
class Mainframe56:
    filesystem   # nested dicts — directories and files
    processes    # list of running process objects
    network      # addresses and listening services
    api          # tier-specific functions
    glitches     # what is broken and how
    state        # tier state and flags
    
    # shared memory — subsystems read/write directly
    # no interrupts needed
    memory = {
        "display":  bytearray(256 * 192),
        "palette":  bytearray(256 * 3),
        "keyboard": bytearray(256),
        "storage":  bytearray(1024 * 1024),
        "sound":    bytearray(64),
    }
```

---

### The Adventure Engine

The game is a text adventure with Hobbit-style graphics. The text adventure engine runs on the T46 in the built-in language. It is simple enough that the player who gets deep enough can read its source code. This is intentional. The adventure system is a library that is reachable by the pi code. whatever is not implemented can be implemented in pi code.

**The core engine (Quill-style):**
```python
struct Location:
    description
    exits        # dict: direction -> location_id
    objects      # list of object ids here

struct Object:
    name
    description
    location     # location_id, INVENTORY, or NOWHERE
    flags        # properties dict

flags = [0] * 256     # the game's memory
player_location = 0

def game_loop():
    describe_location(player_location)
    while true:
        input = get_input("> ")
        verb, noun = parse(input)
        process_response(verb, noun)
```


**The T46 in Pygame:**

```python
import pygame

class T46:
    WIDTH  = 256
    HEIGHT = 192
    SCALE  = 3

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode(
            (self.WIDTH  * self.SCALE,
             self.HEIGHT * self.SCALE),
            pygame.NOFRAME
        )
        # 8-bit indexed surface — 1 byte per pixel
        self.fb = pygame.Surface(
            (self.WIDTH, self.HEIGHT),
            depth=8
        )
        self.fb.set_palette(load_doom_palette())

    def receive(self, command):
        match command['type']:
            case 'clear':
                self.fb.fill(command['colour'])
            case 'line':
                pygame.draw.line(
                    self.fb,
                    command['colour'],
                    (command['x1'], command['y1']),
                    (command['x2'], command['y2'])
                )
            case 'fill':
                flood_fill(self.fb,
                           command['x'],
                           command['y'],
                           command['colour'])
            case 'text':
                draw_text(self.fb,
                          command['x'],
                          command['y'],
                          command['string'],
                          command['colour'])
        self._blit()

    def _blit(self):
        scaled = pygame.transform.scale(
            self.fb,
            (self.WIDTH  * self.SCALE,
             self.HEIGHT * self.SCALE)
        )
        self.screen.blit(scaled, (0, 0))
        pygame.display.flip()

    def poll(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type == pygame.KEYDOWN:
                return event.key
        return False
```

**main.py:**

```python
from t46 import T46
from m56 import M56

terminal = T46()
computer = M56(terminal)

computer.connect()

while terminal.running:
    key = terminal.poll()
    if key:
        computer.receive_input(key)
```

