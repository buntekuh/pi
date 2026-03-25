# Pi — Language Design

Pi is a Forth dialect. It is the general-purpose language of the M56 system.
Grue compiles to Pi. Pi compiles to M56 machine code.

The stack is always visible. Pi adds syntactic sugar over bare Forth to make
the language more readable without hiding what it is. For anything Pi cannot
express, the user drops to M56 assembly. That is the point — the machine is
always reachable.

```
Grue  →  Pi  →  M56 machine code
              ↑
         you are here
```


## The stack

Pi is concatenative. Every word consumes and produces values on the stack.
Words are separated by whitespace. Execution is left to right.

    3 4 +           // stack: 7
    3 4 + 2 *       // stack: 14
    "hello" print   // prints hello, stack: empty

Type signatures document the stack effect. They are optional but encouraged:

    ( Int Int -> Int )    // takes two ints, returns one
    ( Str -> )            // takes a string, returns nothing
    ( -> Int )            // produces an int from nothing
    ( -> )                // side effects only


## Definitions

    function double ( Int -> Int ):
        2 *
    end

    function square ( Int -> Int ):
        dup *
    end

    function abs ( Int -> Int ):
        dup 0 <
        if: neg end
    end

For stack-heavy definitions, named locals bind the top of stack to names.
The rightmost name gets the top of stack — matching left-to-right type
signature order. Names are arbitrary.

    // stack arriving: 3 4  (4 on top)
    // -> width height:  gives  width=3  height=4
    function area ( Int Int -> Int ):
        -> width height:
        width height *
    end

    function hypotenuse ( Int Int -> Int ):
        -> a b:
        a a *  b b *  +
    end

    function max ( Int Int -> Int ):
        -> a b:
        if a b >:  a  else:  b  end
    end

Locals are sugar — they compile to stack shuffles. Use them when `dup swap
over rot` becomes harder to read than it is worth.


## Inline macros

The terse `: name ... ;` form defines an inline macro — expanded at the call
site, no CAL instruction generated, no call overhead. Use for small reusable
stack operations where the abstraction cost should be zero.

    : double   2 * ;
    : negate   0 swap - ;
    : square   dup * ;
    : ?dup     dup 0 != if: dup end ;

The Forth syntax is intentional. It signals closeness to the machine and
preserves the connection to Forth literature. A full `function` is a named
abstraction; a macro is just a shorthand.

    // these are equivalent at the machine level:
    3 double            // expands to:  3 2 *
    3 2 *               // same output, same instructions


## Control flow

    if condition:
        ...
    elsif condition:
        ...
    else:
        ...
    end

    while condition:
        ...
    end


## Quotations

A quotation is an anonymous word — a block of code as a value on the stack.

    { dup * }               // pushes a quotation
    { dup * } call          // calls it: squares top of stack
    3 { dup * } call        // stack: 9

Higher-order words take quotations:

    [ 1 2 3 4 5 ] { . } each       // prints 1 2 3 4 5
    [ 1 2 3 4 5 ] { 2 * } map      // stack: [ 2 4 6 8 10 ]
    [ 1 2 3 4 5 ] { 2 mod 0 == } filter  // stack: [ 2 4 ]
    [ 1 2 3 4 5 ] 0 { + } fold     // stack: 15


## Lists

    [ 1 2 3 ]               // integer list
    [ "cat" "dog" "fish" ]  // string list
    [ ]                     // empty list

    [ 1 2 3 ] length        // 3
    [ 1 2 3 ] first         // 1
    [ 1 2 3 ] rest          // [ 2 3 ]
    1 [ 2 3 ] cons          // [ 1 2 3 ]


## Variables and constants

    variable counter
    0 counter !         // store
    counter @           // fetch
    counter @ 1 + counter !

    42 constant answer


## Cells and integers

A cell is 16 bits — the width of an M56 register and the natural unit of the
stack. Integers are signed 16-bit, range −32768 to 32767. Memory words (`@`
`!`) operate on cells; `c@` `c!` operate on single bytes.

Pi has no floating point. All arithmetic is integer. This is a feature — it
keeps the language honest, the implementation simple, and the machine model
transparent.

Arithmetic wraps silently on overflow — `32767 1 +` gives `-32768`. This is
not an error; it is how 16-bit hardware behaves. Signed vs unsigned is a
property of the operation, not the value: `<` interprets bits as signed,
`u<` interprets the same bits as unsigned. The programmer is responsible for
knowing which they need.

Decimal literals are signed. Hex literals are unsigned. The distinction
reflects intent — decimal for values, hex for bit patterns, addresses, and
hardware constants:

    -1          // signed: negative one
    0xffff      // unsigned: 65535  (same bit pattern, different meaning)
    0x1a        // unsigned: port number, colour index, memory address

Unsigned arithmetic words carry a `u` prefix — same bits, different
interpretation:

    u<  u>  u/  umod    // unsigned comparisons and division


## Strings

Strings are first-class values. They are not null-terminated C strings — the
length is stored with the data.

    "hello world" print
    "hello" " world" concat print   // "hello world"
    "hello" length                  // 5
    "hello" 1 nth                   // "e"  (0-indexed)


## Conversions

    // integer to decimal string
    42 int-to-str          // "42"
    -7 int-to-str          // "-7"

    // integer to hex string
    255 int-to-hex         // "ff"
    255 int-to-HEX         // "FF"

    // string to integer  (fails with error on bad input)
    "42"  str-to-int       // 42
    "ff"  hex-to-int       // 255

    // integer to bool
    0 int-to-bool          // false
    1 int-to-bool          // true

    // format: {} is replaced by the next stack value converted to string
    "x={} y={}" [ 3 7 ] format     // "x=3 y=7"


## Naming rules

Identifiers use `[a-zA-Z_][a-zA-Z0-9_-]*` — letters, digits, underscores,
and hyphens. Hyphens are idiomatic for multi-word names:

    go-north    speak-dog    max-rooms    str-to-int

Rules:
- Must start with a letter or underscore — not a digit or hyphen
- Hyphens in the middle or end are fine; leading hyphen is ambiguous with
  negative integer literals (`-1`) and is not allowed
- Case sensitive — `Room` and `room` are different words
- Namespace separator `.` is not part of a name: `animals.speak` is the
  word `speak` inside namespace `animals`

This also means the conversion words lose the `>` shorthand and use
`-to-` instead: `str-to-int`, `int-to-str`, `int-to-hex`.


## Comments

    // single line comment

    /* multi-line
       comment */


## Namespaces

A namespace groups related functions and keeps them out of the global
dictionary. Access with dot notation, or bring them into scope with `use`.

    namespace animals:
        function speak-dog ( -> ): "woof" print end
        function speak-cat ( -> ): "miaow" print end
    end

    animals.speak-dog       // qualified access
    animals.speak-cat

    use animals             // import into current scope
    speak-dog               // now unqualified

The Grue runtime lives in its own namespace so it does not collide with
user code.


## Standard words

Inherited from Forth. A selection:

    Stack       dup  drop  swap  over  rot  nip  tuck
    Arithmetic  +  -  *  /  mod  neg  abs
    Comparison  ==  !=  <  >  <=  >=
    Logic       and  or  not
    Memory      @  !  c@  c!  here  allot
    I/O         print  println  .  emit  key
    Conversion  int-to-str  int-to-hex  int-to-HEX  str-to-int  hex-to-int  int-to-bool  format


## Errors

`error` halts execution immediately with a message:

    error "division by zero"
    error "index out of bounds"

For operations that can fail gracefully, functions return a success flag as
the top of stack — by convention `( args -> result ok? )`:

    "42"  str-to-int       // stack: 42 true
    "abc" str-to-int       // stack: 0  false

    "42" str-to-int
    if:
        // use the result
    else:
        error "bad integer input"
    end

The runtime raises errors for: division by zero, stack underflow, out of
bounds memory access, and type mismatches on checked operations.

`panic` is for code that should be impossible to reach. It halts immediately
with no recovery — a bug in the program, not a bad input:

    // exhaustive direction handler
    if dir == north:   go-north
    elsif dir == south: go-south
    elsif dir == east:  go-east
    elsif dir == west:  go-west
    else: panic "unreachable direction"
    end

`error` is for expected failures the program could handle.
`panic` is for invariant violations that indicate a bug.


## Not yet decided

- **try/catch** — error recovery further up the call stack. Useful but adds
  runtime complexity. Defer until the basic interpreter is working.

- **Structs** — named fields instead of raw memory offsets. Something like
  `struct point: x Int  y Int end` with dot access `p.x`. Would make the
  Grue runtime much cleaner. Worth adding once the core language is stable.

- **Switch/match** — pattern matching over a value, cleaner than long
  if/elsif chains. Possibly `match val: case 1: ... case 2: ... else: ... end`.

- **Editor syntax checking** — on Ctrl+S, check `.pi` and `.grue` files and
  show errors in the status bar (`line 4: unexpected end`). The checker is a
  Python function now; later replaced by Pi itself. The editor infrastructure
  is already in place — status bar, file path, save hook.

- **Compile-time evaluation** — `comptime:` constants and/or user-defined
  immediate words (Forth's power move for extending the compiler itself).
  Probably not needed for Pi's scope. Revisit if the need arises.


## Relation to M56 assembly

Pi compiles to M56 machine code. The Forth inner interpreter runs on the M56.
A Pi function is, at its simplest, a sequence of M56 CAL instructions.

The M56 is always reachable. Pi is not a cage. A future learning tool will
let Pi functions emit annotated M56 assembly so the user can see exactly what
the compiler produced — a direct window from Pi down to the machine.
