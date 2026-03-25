"""
Tests for pi_interp.py (Step 2 — stack + arithmetic).

Run with:  python3 -m pytest tests/
      or:  python3 tests/test_interp.py
"""

import io
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pi_interp import Interpreter, InterpError
from pi_lexer import LexError
import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run(source: str) -> tuple[str, list]:
    """Run source, return (output_text, final_stack)."""
    buf = io.StringIO()
    interp = Interpreter(output=buf.write)
    interp.run(source)
    return buf.getvalue(), interp.stack


# ---------------------------------------------------------------------------
# Integer literals
# ---------------------------------------------------------------------------

def test_push_positive():
    _, s = run("42")
    assert s == [42]

def test_push_negative():
    _, s = run("-7")
    assert s == [-7]

def test_push_hex():
    _, s = run("0xff")
    assert s == [255]

def test_push_hex_max():
    # 0xffff is wrapped to -1 when stored in a 16-bit signed cell
    _, s = run("0xffff")
    assert s == [-1]

def test_hex_equals_signed():
    # 0xffff and -1 are the same bit pattern — they must compare equal
    _, s = run("0xffff -1 ==")
    assert s == [-1]   # true


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------

def test_add():
    _, s = run("2 3 +")
    assert s == [5]

def test_sub():
    _, s = run("10 3 -")
    assert s == [7]

def test_mul():
    _, s = run("4 5 *")
    assert s == [20]

def test_div_truncates_toward_zero():
    _, s = run("7 2 /")
    assert s == [3]
    _, s = run("-7 2 /")
    assert s == [-3]

def test_mod():
    _, s = run("7 2 mod")
    assert s == [1]

def test_overflow_wraps():
    _, s = run("32767 1 +")
    assert s == [-32768]
    _, s = run("-32768 1 -")
    assert s == [32767]

def test_neg():
    _, s = run("5 neg")
    assert s == [-5]
    _, s = run("5 negate")
    assert s == [-5]

def test_abs():
    _, s = run("-7 abs")
    assert s == [7]
    _, s = run("7 abs")
    assert s == [7]


# ---------------------------------------------------------------------------
# Stack operations
# ---------------------------------------------------------------------------

def test_dup():
    _, s = run("3 dup")
    assert s == [3, 3]

def test_drop():
    _, s = run("1 2 drop")
    assert s == [1]

def test_swap():
    _, s = run("1 2 swap")
    assert s == [2, 1]

def test_over():
    _, s = run("1 2 over")
    assert s == [1, 2, 1]

def test_rot():
    _, s = run("1 2 3 rot")
    assert s == [2, 3, 1]

def test_nip():
    _, s = run("1 2 nip")
    assert s == [2]

def test_tuck():
    _, s = run("1 2 tuck")
    assert s == [2, 1, 2]

def test_depth():
    _, s = run("1 2 3 depth")
    assert s == [1, 2, 3, 3]


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def test_eq_true():
    _, s = run("4 4 ==")
    assert s == [-1]

def test_eq_false():
    _, s = run("3 4 ==")
    assert s == [0]

def test_ne():
    _, s = run("3 4 !=")
    assert s == [-1]

def test_lt():
    _, s = run("3 4 <")
    assert s == [-1]
    _, s = run("4 3 <")
    assert s == [0]

def test_gt():
    _, s = run("4 3 >")
    assert s == [-1]

def test_le():
    _, s = run("3 3 <=")
    assert s == [-1]

def test_ge():
    _, s = run("3 3 >=")
    assert s == [-1]


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

def test_and():
    _, s = run("-1 -1 and")
    assert s == [-1]
    _, s = run("-1 0 and")
    assert s == [0]

def test_or():
    _, s = run("0 -1 or")
    assert s == [-1]
    _, s = run("0 0 or")
    assert s == [0]

def test_not_true():
    # not of -1 (all ones) = 0
    _, s = run("-1 not")
    assert s == [0]

def test_not_false():
    # not of 0 = -1
    _, s = run("0 not")
    assert s == [-1]


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def test_dot_prints_with_space():
    out, _ = run("42 .")
    assert out == "42 "

def test_print():
    out, _ = run('"hello" print')
    assert out == "hello"

def test_println():
    out, _ = run('"hello" println')
    assert out == "hello\n"

def test_emit():
    out, _ = run("0x4F emit 0x4B emit")
    assert out == "OK"

def test_print_integer():
    out, _ = run("42 print")
    assert out == "42"


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------

def test_concat():
    _, s = run('"hello" " world" concat')
    assert s == ["hello world"]

def test_length_string():
    _, s = run('"hello" length')
    assert s == [5]

def test_int_to_str():
    _, s = run("42 int-to-str")
    assert s == ["42"]

def test_int_to_hex():
    _, s = run("255 int-to-hex")
    assert s == ["ff"]

def test_int_to_HEX():
    _, s = run("255 int-to-HEX")
    assert s == ["FF"]

def test_str_to_int_ok():
    _, s = run('"42" str-to-int')
    assert s == [42, -1]   # value, true

def test_str_to_int_fail():
    _, s = run('"abc" str-to-int')
    assert s == [0, 0]     # 0, false

def test_nth():
    _, s = run('"hello" 1 nth')
    assert s == ["e"]


# ---------------------------------------------------------------------------
# String literal push
# ---------------------------------------------------------------------------

def test_push_string():
    _, s = run('"hello world"')
    assert s == ["hello world"]

def test_push_string_escape():
    _, s = run('"line\\none"')
    assert s == ["line\none"]


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_stack_underflow():
    with pytest.raises(InterpError, match="stack underflow"):
        run("+")

def test_division_by_zero():
    with pytest.raises(InterpError, match="division by zero"):
        run("5 0 /")

def test_unknown_word():
    with pytest.raises(InterpError, match="unknown word"):
        run("frobnicate")


# ---------------------------------------------------------------------------
# Step 3 — : ; macro definitions
# ---------------------------------------------------------------------------

def test_macro_simple():
    _, s = run(": double  2 * ;  3 double")
    assert s == [6]

def test_macro_dup_based():
    _, s = run(": square  dup * ;  5 square")
    assert s == [25]

def test_macro_calls_macro():
    _, s = run(": square  dup * ;  : cube  dup square * ;  3 cube")
    assert s == [27]

def test_macro_repeated_call():
    _, s = run(": inc  1 + ;  0 inc inc inc")
    assert s == [3]

def test_macro_redefine():
    # Later definition of same name wins
    _, s = run(": double  2 * ;  : double  dup + ;  4 double")
    assert s == [8]

def test_macro_overrides_builtin():
    # User can shadow a builtin
    _, s = run(": abs  drop 42 ;  -7 abs")
    assert s == [42]

def test_macro_output():
    out, _ = run(': greet  "hello" println ;  greet greet')
    assert out == "hello\nhello\n"

def test_macro_unterminated():
    with pytest.raises(InterpError, match="unterminated"):
        run(": oops  1 2 +")

def test_macro_missing_name():
    with pytest.raises(InterpError):
        run(": 42 ;")


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------

def test_fixed_point_pi():
    """355 */ 10000 / 113 gives pi to 4 decimal places via 32-bit intermediate."""
    _, s = run("355 10000 113 */")
    assert s == [31415]

def test_muldiv():
    """a*b/c with 32-bit intermediate."""
    _, s = run("3 10000 4 */")
    assert s == [7500]   # 3 * 10000 / 4 = 7500

def test_chain():
    out, _ = run('2 3 + dup * int-to-str println')
    assert out == "25\n"


# ---------------------------------------------------------------------------
# Step 4 — control flow
# ---------------------------------------------------------------------------

def test_if_true():
    out, _ = run('-1 if: "yes" println end')
    assert out == "yes\n"

def test_if_false():
    out, _ = run('0 if: "yes" println end')
    assert out == ""

def test_if_else_true():
    out, _ = run('-1 if: "yes" println else: "no" println end')
    assert out == "yes\n"

def test_if_else_false():
    out, _ = run('0 if: "yes" println else: "no" println end')
    assert out == "no\n"

def test_if_inline_condition():
    out, _ = run('3 4 < if: "lt" println end')
    assert out == "lt\n"

def test_if_inline_condition_false():
    out, _ = run('4 3 < if: "lt" println end')
    assert out == ""

def test_elsif_first_branch():
    out, _ = run('12 dup 10 > if: "big" elsif 5 >: "mid" else: "small" end println')
    assert out == "big\n"

def test_elsif_middle_branch():
    out, _ = run('7 dup 10 > if: "big" elsif 5 >: "mid" else: "small" end println')
    assert out == "mid\n"

def test_elsif_else_branch():
    out, _ = run('5 dup 10 > if: "big" elsif 5 >: "mid" else: "small" end println')
    assert out == "small\n"

def test_if_no_else_false_leaves_nothing():
    # False branch with no else: stack unchanged, no output
    _, s = run('1 2 3  0 if: drop end')
    assert s == [1, 2, 3]

def test_nested_if():
    out, _ = run('''
        -1 if:
            -1 if: "inner" println end
        end
    ''')
    assert out == "inner\n"

def test_nested_if_outer_false():
    out, _ = run('''
        0 if:
            -1 if: "inner" println end
        end
    ''')
    assert out == ""

def test_while_counts_down():
    out, _ = run('5 while dup 0 >: dup . 1 - end drop')
    assert out == "5 4 3 2 1 "

def test_while_zero_iterations():
    out, _ = run('0 while dup 0 >: dup . 1 - end drop')
    assert out == ""

def test_while_accumulate():
    # sum 1..5:  stack is  acc counter  (counter on top)
    # body: swap over + swap 1 -  →  (acc+counter) (counter-1)
    _, s = run('0 5 while dup 0 >: swap over + swap 1 - end drop')
    assert s == [15]

def test_if_in_while():
    # print even numbers 1..6
    out, _ = run('6 while dup 0 >: dup 2 mod 0 == if: dup . end 1 - end drop')
    assert out == "6 4 2 "

def test_macro_with_if():
    out, _ = run(': abs-val  dup 0 < if: neg end ;  -5 abs-val .')
    assert out == "5 "

def test_error_word():
    with pytest.raises(InterpError, match="oops"):
        run('"oops" error')

def test_panic_word():
    with pytest.raises(InterpError, match="panic"):
        run('"bad state" panic')


# ---------------------------------------------------------------------------
# Step 5 — function definitions and named locals
# ---------------------------------------------------------------------------

def test_local_single():
    _, s = run('5 -> x:  x x *')
    assert s == [25]

def test_local_multiple_order():
    # rightmost name = top of stack
    _, s = run('3 4 -> width height:  width height *')
    assert s == [12]

def test_local_reassign():
    _, s = run('0 -> count:  count 1 + -> count:  count 1 + -> count:  count')
    assert s == [2]

def test_function_basic():
    _, s = run('function double ( Int -> Int ): 2 * end  7 double')
    assert s == [14]

def test_function_with_locals():
    _, s = run('function area ( Int Int -> Int ): -> w h: w h * end  3 4 area')
    assert s == [12]

def test_function_calls_function():
    src = '''
        function sq   ( Int -> Int ): dup * end
        function cube ( Int -> Int ): -> n: n n sq * end
        3 cube
    '''
    _, s = run(src)
    assert s == [27]

def test_function_locals_dont_leak():
    # x inside f must not clobber x in the caller's frame
    src = 'function f ( -> ): 99 -> x: end  0 -> x:  f  x'
    _, s = run(src)
    assert s == [0]

def test_function_with_if():
    src = '''
        function abs-val ( Int -> Int ):
            dup 0 < if: neg end
        end
        -7 abs-val
    '''
    _, s = run(src)
    assert s == [7]

def test_function_with_while_and_locals():
    src = '''
        function sum-to ( Int -> Int ):
            -> n:
            0 -> acc:
            while n 0 >:
                acc n + -> acc:
                n 1 - -> n:
            end
            acc
        end
        5 sum-to
    '''
    _, s = run(src)
    assert s == [15]

def test_function_no_sig():
    # Type signature is optional
    _, s = run('function inc: 1 + end  41 inc')
    assert s == [42]

def test_macro_with_locals():
    # : ; macros can also use locals
    _, s = run(': swap2  -> a b: b a ;  1 2 swap2')
    assert s == [2, 1]

def test_function_multiple_calls_independent():
    # Each call gets a clean frame; counter must not persist between calls
    src = '''
        function count3 ( -> Int ):
            0 -> c:
            c 1 + -> c:
            c 1 + -> c:
            c 1 + -> c:
            c
        end
        count3 count3 +
    '''
    _, s = run(src)
    assert s == [6]   # 3 + 3

def test_function_if_elsif_else():
    src = '''
        function classify ( Int -> Str ):
            -> n:
            if n 0 <:    "negative"
            elsif n 0 ==: "zero"
            else:         "positive"
            end
        end
        -1 classify
        0  classify
        1  classify
    '''
    _, s = run(src)
    assert s == ["negative", "zero", "positive"]


# ---------------------------------------------------------------------------
# Step 6 — variables, constants, @ !
# ---------------------------------------------------------------------------

def test_variable_store_fetch():
    _, s = run('variable x  42 x !  x @')
    assert s == [42]

def test_variable_init_zero():
    _, s = run('variable x  x @')
    assert s == [0]

def test_variable_increment():
    _, s = run('variable counter  0 counter !  counter @ 1 + counter !  counter @')
    assert s == [1]

def test_constant():
    _, s = run('42 constant answer  answer answer +')
    assert s == [84]

def test_constant_hex():
    _, s = run('0x2D constant dash  dash')
    assert s == [-1 & 0x2D - (0x10000 if 0x2D >= 0x8000 else 0)]
    # 0x2D = 45, fits in positive range
    _, s = run('0x2D constant dash  dash')
    assert s == [45]

def test_two_variables_independent():
    _, s = run('variable a  variable b  1 a !  2 b !  a @ b @ +')
    assert s == [3]

def test_variable_wrap_on_store():
    # 0x8000 = 32768 unsigned, stored as -32768 in a signed 16-bit cell
    _, s = run('variable x  0x8000 x !  x @')
    assert s == [-32768]


# ---------------------------------------------------------------------------
# Step 7 — format string
# ---------------------------------------------------------------------------

def test_format_basic():
    _, s = run('"x={} y={}" [ 3 7 ] format')
    assert s == ["x=3 y=7"]

def test_format_single():
    _, s = run('"hello {}" [ "world" ] format')
    assert s == ["hello world"]

def test_format_empty():
    _, s = run('"no placeholders" [ ] format')
    assert s == ["no placeholders"]


# ---------------------------------------------------------------------------
# Step 8 — lists and quotations
# ---------------------------------------------------------------------------

def test_list_literal():
    _, s = run('[ 1 2 3 ]')
    assert s == [[1, 2, 3]]

def test_list_empty():
    _, s = run('[ ]')
    assert s == [[]]

def test_list_strings():
    _, s = run('[ "cat" "dog" ]')
    assert s == [["cat", "dog"]]

def test_list_length():
    _, s = run('[ 1 2 3 ] length')
    assert s == [3]

def test_list_first():
    _, s = run('[ 10 20 30 ] first')
    assert s == [10]

def test_list_rest():
    _, s = run('[ 10 20 30 ] rest')
    assert s == [[20, 30]]

def test_list_cons():
    _, s = run('1 [ 2 3 ] cons')
    assert s == [[1, 2, 3]]

def test_list_nth():
    _, s = run('[ 10 20 30 ] 1 nth')
    assert s == [20]

def test_quotation_call():
    _, s = run('5 { dup * } call')
    assert s == [25]

def test_quotation_call_with_locals():
    _, s = run('3 { -> n: n n * } call')
    assert s == [9]

def test_each():
    out, _ = run('[ 1 2 3 ] { . } each')
    assert out == "1 2 3 "

def test_map():
    _, s = run('[ 1 2 3 ] { 2 * } map')
    assert s == [[2, 4, 6]]

def test_filter():
    _, s = run('[ 1 2 3 4 5 ] { 2 mod 0 == } filter')
    assert s == [[2, 4]]

def test_fold_sum():
    _, s = run('[ 1 2 3 4 5 ] 0 { + } fold')
    assert s == [15]

def test_fold_product():
    _, s = run('[ 1 2 3 4 ] 1 { * } fold')
    assert s == [24]

def test_map_then_fold():
    _, s = run('[ 1 2 3 ] { dup * } map  0 { + } fold')
    assert s == [14]   # 1 + 4 + 9

def test_each_with_function():
    src = '''
        function double-print ( Int -> ):
            2 * int-to-str println
        end
        [ 1 2 3 ] { double-print } each
    '''
    out, _ = run(src)
    assert out == "2\n4\n6\n"

def test_quotation_in_function():
    src = '''
        function apply ( Int -> Int ):
            -> n:
            n { dup * } call
        end
        5 apply
    '''
    _, s = run(src)
    assert s == [25]


# ---------------------------------------------------------------------------
# Step 9 — namespaces
# ---------------------------------------------------------------------------

def test_namespace_qualified_call():
    src = '''
        namespace math:
            function double ( Int -> Int ): 2 * end
        end
        5 math.double
    '''
    _, s = run(src)
    assert s == [10]

def test_namespace_use():
    src = '''
        namespace math:
            function double ( Int -> Int ): 2 * end
        end
        use math
        5 double
    '''
    _, s = run(src)
    assert s == [10]

def test_namespace_multiple_words():
    src = '''
        namespace vec:
            function add ( Int Int -> Int ): + end
            function scale ( Int Int -> Int ): * end
        end
        3 4 vec.add
        5 vec.scale
    '''
    _, s = run(src)
    assert s == [35]

def test_namespace_calls_sibling():
    # Words inside a namespace can call each other by short name during definition
    src = '''
        namespace math:
            function sq ( Int -> Int ): dup * end
            function sum-of-squares ( Int Int -> Int ):
                -> a b:
                a sq b sq +
            end
        end
        3 4 math.sum-of-squares
    '''
    _, s = run(src)
    assert s == [25]

def test_namespace_doesnt_pollute_global():
    src = '''
        namespace ns:
            function helper ( -> Int ): 99 end
        end
    '''
    with pytest.raises(InterpError, match="unknown word 'helper'"):
        run(src + '  helper')

def test_namespace_variable():
    src = '''
        namespace state:
            variable counter
        end
        42 state.counter !
        state.counter @
    '''
    _, s = run(src)
    assert s == [42]

def test_namespace_constant():
    src = '''
        namespace cfg:
            10000 constant SCALE
        end
        3 cfg.SCALE *
    '''
    _, s = run(src)
    assert s == [30000]

def test_use_imports_constant():
    src = '''
        namespace cfg:
            10000 constant SCALE
        end
        use cfg
        3 SCALE *
    '''
    _, s = run(src)
    assert s == [30000]


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
