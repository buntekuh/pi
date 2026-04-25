# Titania-0

Titania-0 is the first compiled language in the Titania stack. It is typeless —
everything is a 32-bit word — and compiles directly to M56 assembly. Its
compiler is written in M56 assembly and is simple enough to be understood in
one sitting.

The language is designed for execution speed. Every construct maps almost
one-to-one to a specific M56 instruction — there is no hidden overhead, no
runtime, no garbage collector. This is the same philosophy that drove BCPL and
Dennis Ritchie's original C for the PDP-7: design the language around what the
hardware does naturally, and the compiler becomes trivial while the output
becomes fast.

The language looks like C. Anyone who has written C, JavaScript, or Arduino
sketches will feel at home immediately.

---

## Variables

All variables must be declared with `let` and must be initialised. There are no
types — every variable holds a 32-bit word.

```c
let x = 5
let y = x + 1
let z = 0
```

Declaring a variable without an initialiser is a compiler error.

---

## Arithmetic and operators

Standard C operators. All arithmetic is 32-bit integer.

```c
let a = x + y
let b = x - y
let c = x * y
let d = x / y
let e = x % y
```

Bitwise:

```c
let a = x & y     // AND
let b = x | y     // OR
let c = x ^ y     // XOR
let d = ~x        // NOT
let e = x << 2    // shift left
let f = x >> 2    // shift right
```

Comparison operators return 1 (true) or 0 (false):

```c
x == y
x != y
x <  y
x >  y
x <= y
x >= y
```

---

## Pointers

A pointer is just a word that holds an address. The compiler does not
distinguish between pointers and integers — the programmer does.

```c
let x = 5
let p = &x        // p holds the address of x
*p = 99           // write 99 to the address held in p
let y = *p        // read from the address held in p
```

Indexed access — maps directly to M56 mode 4/5:

```c
let c = s[0]      // read word at address s + 0
let c = s[3]      // read word at address s + 3
s[1] = 42         // write 42 to address s + 1
```

String literals are pointers to null-terminated byte sequences in the data
segment:

```c
let s = "hello"   // s holds the address of 'h'
let c = s[0]      // c = 0x68 ('h')
```

---

## Control flow

### if

```c
if (x > 0) {
    x = x - 1
}

if (x == 0) {
    foo()
} else {
    bar()
}
```

### while

```c
while (x > 0) {
    x = x - 1
}
```

### for

```c
for (let i = 0; i < 10; i++) {
    s[i] = 0
}
```

---

## Functions

Functions are declared with a name, a parameter list, and a body. Parameters
are words — no types.

```c
add(a, b) {
    return a + b
}

let result = add(3, 4)
```

Functions may call other functions and themselves recursively. The return value
is a single word.

```c
factorial(n) {
    if (n == 0) {
        return 1
    }
    return n * factorial(n - 1)
}
```

A function with no return value simply omits `return`, or returns with no
expression:

```c
clear(p, len) {
    for (let i = 0; i < len; i++) {
        p[i] = 0
    }
}
```

---

## Globals

Variables declared outside any function are global — they live at fixed
addresses in RAM and are visible to all functions.

```c
let counter = 0

increment() {
    counter = counter + 1
}
```

---

## Arrays

Arrays are declared by size. The variable holds the address of the first
element.

```c
let buf[64]       // 64 words of storage, buf points to the first
buf[0] = 1
buf[1] = 2
```

---

## ROM routines

Titania-0 has no standard library, but the ROM exposes a set of built-in
routines callable like any function. Output goes to the UART, which the host
desktop displays.

```c
print("hello world\n")   // send null-terminated string to UART
print(s)                 // s is a pointer to a null-terminated string

printnum(42)             // print integer as decimal: "42"
printnum(x)             // print value of x
```

These are the minimum needed to make programs observable. Everything else —
string manipulation, arithmetic helpers — is either written in Titania-0 or
called via the kernel call table directly.

---

## Comments

```c
// single line comment
```

---

## What Titania-0 does not have

- Types — everything is a 32-bit word
- Structs — use pointer arithmetic and convention
- Floating point — not in the M56 hardware
- Standard library — use ROM routines or write your own
- Preprocessor — no macros, no includes

These are not oversights. They are the pain points that motivate Titania-1.

---

## Mapping to M56

Every Titania-0 construct has an obvious M56 translation. The compiler is
transparent by design.

| Titania-0 | M56 |
|-----------|-----|
| `let x = 5` | `Move #5, Rx` |
| `x + y` | `Add Rx, Ry` |
| `*p` | `Move [Rp], Rd` — mode 2 |
| `s[i]` | `Move [Rs+i], Rd` — mode 4 |
| `if (x > 0)` | `Sub Rx, #0 ; Jump.Nn label` |
| `while` | compare + conditional jump |
| `foo(a, b)` | push args, `Call.Al foo` |
| `return x` | move result to R0, `Ret.Al` |
