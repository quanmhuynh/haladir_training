"""
ACSL Specification Injection Module

This module provides functionality to reinject ACSL (ANSI/ISO C Specification Language)
specifications back into C function implementations, including function specs and loop invariants.

The spec array structure is:
    spec[0]    = List of predicate strings
    spec[1]    = ACSL spec for the 1st function
    spec[2]    = Loop invariant block for 1st loop in 1st function (if any)
    spec[3]    = Loop invariant block for 2nd loop in 1st function (if any)
    spec[4]    = ACSL spec for the 2nd function
    spec[5]    = Loop invariant block for 1st loop in 2nd function (if any)
    ...and so on

Example:
    A file with 2 functions where the first has 2 loops:
        - spec[0]: predicates array (can be empty [])
        - spec[1]: ACSL spec for first function
        - spec[2]: Loop invariant for first loop in first function
        - spec[3]: Loop invariant for second loop in first function
        - spec[4]: ACSL spec for second function
"""

import re
from typing import List, Tuple, Optional


def _find_function_bounds(c_code: str, function_start: int) -> Tuple[int, int]:
    """Find the start and end positions of a function body given its opening brace position."""
    brace_count = 1
    pos = function_start + 1
    
    while pos < len(c_code) and brace_count > 0:
        if c_code[pos] == '{':
            brace_count += 1
        elif c_code[pos] == '}':
            brace_count -= 1
        pos += 1
    
    return function_start, pos - 1


def _find_loops_in_range(c_code: str, start_pos: int, end_pos: int) -> List[Tuple[int, int]]:
    """Find all loop constructs (while/for) within a given range and return their positions."""
    loops = []
    
    while_pattern = r'\bwhile\s*\('
    for_pattern = r'\bfor\s*\('
    
    for match in re.finditer(while_pattern, c_code[start_pos:end_pos]):
        loop_start = start_pos + match.start()
        loops.append(('while', loop_start))
    
    for match in re.finditer(for_pattern, c_code[start_pos:end_pos]):
        loop_start = start_pos + match.start()
        loops.append(('for', loop_start))
    
    return sorted(loops, key=lambda x: x[1])


def inject_acsl_specs(spec: List, c_code: str) -> str:
    """
    Inject ACSL specifications back into C function implementations.
    
    Args:
        spec: A list where spec[0] is predicates list and spec[1:] are function specs
              and loop invariant blocks in order (function spec, then its loop invariants, etc.)
        c_code: The C code without ACSL specifications
    
    Returns:
        The C code with all ACSL specifications injected in their proper positions.
    """
    if not c_code or not isinstance(c_code, str):
        return c_code if c_code else ""
    
    if not spec or len(spec) == 0:
        return c_code
    
    predicates: List[str] = spec[0] if spec[0] else []
    remaining_specs = spec[1:] if len(spec) > 1 else []
    
    function_pattern = r'((?:static\s+|extern\s+|inline\s+)?(?:\w+\s*\*?\s+)(\w+)\s*\([^)]*\)\s*\{)'
    function_matches = list(re.finditer(function_pattern, c_code))
    
    if len(function_matches) == 0:
        predicates_text = "\n\n".join(pred.strip() for pred in predicates if pred and pred.strip())
        return predicates_text + "\n\n" + c_code if predicates_text else c_code
    
    injection_points = []
    spec_index = 0
    
    for func_idx, func_match in enumerate(function_matches):
        func_start = func_match.start()
        func_body_start = func_match.end() - 1
        func_body_end = _find_function_bounds(c_code, func_body_start)[1]
        
        if spec_index >= len(remaining_specs):
            break
        
        func_spec = remaining_specs[spec_index]
        spec_index += 1
        
        if func_spec and func_spec.strip():
            injection_points.append((func_start, func_spec.strip(), 'function'))
        
        loops = _find_loops_in_range(c_code, func_body_start, func_body_end)
        
        for loop_type, loop_start in loops:
            if spec_index >= len(remaining_specs):
                break
            
            loop_spec = remaining_specs[spec_index]
            spec_index += 1
            
            if loop_spec and loop_spec.strip():
                injection_points.append((loop_start, loop_spec.strip(), 'loop'))
    
    injected_code = c_code
    injection_points.sort(key=lambda x: x[0], reverse=True)
    for pos, spec_text, spec_type in injection_points:
        injected_code = (
            injected_code[:pos]
            + spec_text
            + "\n"
            + injected_code[pos:]
        )
    
    predicates_text = ""
    if predicates:
        predicates_text = "\n\n".join(pred.strip() for pred in predicates if pred and pred.strip())
    
    final_code = ""
    if predicates_text:
        final_code += predicates_text + "\n\n"
    final_code += injected_code
    
    final_code = re.sub(r'\n\s*\n\s*\n+', '\n\n', final_code)
    final_code = final_code.strip()
    
    return final_code


def inject_acsl_specs_detailed(spec: List, c_code: str) -> Tuple[str, dict]:
    """
    Same as inject_acsl_specs but also returns detailed information about the injection.
    
    Returns:
        A tuple of (injected_code, details_dict) where details_dict contains:
            - 'num_predicates': Number of predicates injected
            - 'num_function_specs': Number of function specs injected
            - 'num_loop_specs': Number of loop invariant specs injected
            - 'functions_found': List of function names found in the code
            - 'predicates': The predicate strings that were injected
            - 'function_specs': The function spec strings that were injected
            - 'loop_specs': The loop invariant spec strings that were injected
    """
    details = {
        'num_predicates': 0,
        'num_function_specs': 0,
        'num_loop_specs': 0,
        'functions_found': [],
        'predicates': [],
        'function_specs': [],
        'loop_specs': []
    }
    
    if not c_code or not isinstance(c_code, str):
        return (c_code if c_code else "", details)
    
    if not spec or len(spec) == 0:
        return (c_code, details)
    
    predicates = spec[0] if spec[0] else []
    details['predicates'] = predicates
    details['num_predicates'] = len(predicates)
    
    remaining_specs = spec[1:] if len(spec) > 1 else []
    
    function_pattern = r'((?:static\s+|extern\s+|inline\s+)?(?:\w+\s*\*?\s+)(\w+)\s*\([^)]*\)\s*\{)'
    function_matches = list(re.finditer(function_pattern, c_code))
    details['functions_found'] = [m.group(2) for m in function_matches]
    
    spec_index = 0
    for func_idx, func_match in enumerate(function_matches):
        func_body_start = func_match.end() - 1
        func_body_end = _find_function_bounds(c_code, func_body_start)[1]
        
        if spec_index >= len(remaining_specs):
            break
        
        func_spec = remaining_specs[spec_index]
        spec_index += 1
        if func_spec and func_spec.strip():
            details['function_specs'].append(func_spec)
        
        loops = _find_loops_in_range(c_code, func_body_start, func_body_end)
        
        for loop_type, loop_start in loops:
            if spec_index >= len(remaining_specs):
                break
            
            loop_spec = remaining_specs[spec_index]
            spec_index += 1
            if loop_spec and loop_spec.strip():
                details['loop_specs'].append(loop_spec)
    
    details['num_function_specs'] = len(details['function_specs'])
    details['num_loop_specs'] = len(details['loop_specs'])
    
    injected_code = inject_acsl_specs(spec, c_code)
    
    return (injected_code, details)


def validate_spec_structure(spec: List) -> Tuple[bool, Optional[str]]:
    """
    Validate that a spec array has the correct structure.
    
    Returns:
        A tuple of (is_valid, error_message).
    """
    if not isinstance(spec, list):
        return (False, "spec must be a list")
    
    if len(spec) == 0:
        return (False, "spec cannot be empty - must have at least predicates list (can be empty [])")
    
    if not isinstance(spec[0], list):
        return (False, "spec[0] (predicates) must be a list")
    
    for i, pred in enumerate(spec[0]):
        if not isinstance(pred, str):
            return (False, f"spec[0][{i}] (predicate) must be a string, got {type(pred)}")
    
    for i, item_spec in enumerate(spec[1:], start=1):
        if not isinstance(item_spec, str):
            return (False, f"spec[{i}] (function/loop spec) must be a string, got {type(item_spec)}")
    
    return (True, None)


if __name__ == "__main__":
    print("=" * 70)
    print("Example 1: Simple function")
    print("=" * 70)
    
    simple_spec = [
        [],
        '/*@ requires v >= min && v <= max;\n    ensures \\result == v;\n */'
    ]
    
    simple_code = """int clamp(int v, int min, int max) {
    int low = v > min ? v : min;
    return low < max ? low : max;
}"""
    
    result = inject_acsl_specs(simple_spec, simple_code)
    print(result)
    print()
    
    print("=" * 70)
    print("Example 2: Function with loop invariants")
    print("=" * 70)
    
    loop_spec = [
        [],
        '/*@ requires n > 0;\n    ensures 0 <= \\result < n;\n */',
        '/*@\n      loop invariant 0 <= i < n;\n      loop invariant 0 <= minInd < n;\n      loop variant n-1-i;\n     */'
    ]
    
    loop_code = """int min_index(int* t, int n) {
    int minInd = 0, i = 0;
    while(i < n-1) {
        if (t[++i] < t[minInd])
            minInd = i;
    }
    return minInd;
}"""
    
    result = inject_acsl_specs(loop_spec, loop_code)
    print(result)
    print()
    
    print("=" * 70)
    print("Example 3: Multiple functions with loops")
    print("=" * 70)
    
    multi_spec = [
        ['/*@ predicate is_positive(int x) = x > 0; */'],
        '/*@ requires x >= 0;\n    ensures \\result >= 0;\n */',
        '/*@\n      loop invariant 0 <= i <= x;\n      loop variant x - i;\n     */',
        '/*@ requires is_positive(n);\n    ensures \\result > 0;\n */'
    ]
    
    multi_code = """int square(int x) {
    int result = 0;
    for (int i = 0; i < x; i++) {
        result += x;
    }
    return result;
}

int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}"""
    
    result, details = inject_acsl_specs_detailed(multi_spec, multi_code)
    print(result)
    print()
    print(f"Details: {details}")
