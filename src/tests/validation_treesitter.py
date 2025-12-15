"""
Tree-sitter based validation for skeleton structure and completion matching.

Workflow:
1. Extract structure from skeleton (using tree-sitter)
2. Extract structure from model completion (using tree-sitter)
3. Compare structures to ensure they match
4. If match: Use tree-sitter to find exact injection points for specs
"""

from tree_sitter import Language, Parser, Node
import tree_sitter_c as tsc
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


# ============================================================================
# Data structures to represent code structure
# ============================================================================

@dataclass
class LoopInfo:
    """Information about a loop in the code."""
    type: str  # 'for', 'while', or 'do'
    header: str  # The loop header text (e.g., "for (int i = 0; i < n; i++)")
    byte_position: int  # Position in source where loop starts
    line_number: int  # Line number where loop starts


@dataclass
class FunctionInfo:
    """Information about a function in the code."""
    name: str
    signature: str  # Full signature including return type
    byte_position: int  # Position where function starts
    line_number: int
    loops: List[LoopInfo]  # Loops within this function, in order


@dataclass
class CodeStructure:
    """Complete structural information about C code."""
    functions: List[FunctionInfo]

    def to_dict(self) -> dict:
        """Convert to dictionary for easier comparison/serialization."""
        return {
            'function_count': len(self.functions),
            'functions': [
                {
                    'name': f.name,
                    'signature': f.signature,
                    'loop_count': len(f.loops),
                    'loop_types': [l.type for l in f.loops],
                    'loop_headers': [l.header for l in f.loops]
                }
                for f in self.functions
            ]
        }


# ============================================================================
# Step 1: Extract structure from code using tree-sitter
# ============================================================================

def extract_structure(c_code: str) -> CodeStructure:
    """
    Extract structural information from C code using tree-sitter.
    This is the foundation for both validation and injection.
    """
    C_LANGUAGE = Language(tsc.language())
    parser = Parser(C_LANGUAGE)

    tree = parser.parse(bytes(c_code, "utf8"))
    source_bytes = c_code.encode('utf8')

    functions = []

    # Find all function definitions
    for node in _find_all_nodes_of_type(tree.root_node, 'function_definition'):
        func_info = _extract_function_info(node, source_bytes, c_code)
        functions.append(func_info)

    return CodeStructure(functions=functions)


def _find_all_nodes_of_type(node: Node, node_type: str) -> List[Node]:
    """Recursively find all nodes of a specific type."""
    results = []

    if node.type == node_type:
        results.append(node)

    for child in node.children:
        results.extend(_find_all_nodes_of_type(child, node_type))

    return results


def _extract_function_info(func_node: Node, source_bytes: bytes, source_str: str) -> FunctionInfo:
    """Extract information about a function from its AST node."""

    # Get function name
    name = _get_function_name(func_node, source_bytes)

    # Get full signature (everything before the opening brace)
    signature = _get_function_signature(func_node, source_bytes)

    # Get position information
    byte_pos = func_node.start_byte
    line_num = source_str[:byte_pos].count('\n') + 1

    # Find the compound_statement (function body)
    body = None
    for child in func_node.children:
        if child.type == 'compound_statement':
            body = child
            break

    # Extract loops within this function
    loops = []
    if body:
        loops = _extract_loops_from_body(body, source_bytes, source_str)

    return FunctionInfo(
        name=name,
        signature=signature,
        byte_position=byte_pos,
        line_number=line_num,
        loops=loops
    )


def _get_function_name(func_node: Node, source_bytes: bytes) -> str:
    """Extract function name from function_definition node."""
    # Look for function_declarator
    for child in func_node.children:
        if child.type == 'function_declarator':
            # The identifier is the function name
            for sub_child in child.children:
                if sub_child.type == 'identifier':
                    return source_bytes[sub_child.start_byte:sub_child.end_byte].decode('utf8')
    return "unknown"


def _get_function_signature(func_node: Node, source_bytes: bytes) -> str:
    """Extract full function signature (return type + name + parameters)."""
    # Everything before the compound_statement
    for child in func_node.children:
        if child.type == 'compound_statement':
            sig_bytes = source_bytes[func_node.start_byte:child.start_byte]
            # Clean up whitespace
            sig = sig_bytes.decode('utf8').strip()
            # Normalize whitespace
            import re
            sig = re.sub(r'\s+', ' ', sig)
            return sig

    # Fallback: entire node text
    return source_bytes[func_node.start_byte:func_node.end_byte].decode('utf8').strip()


def _extract_loops_from_body(body_node: Node, source_bytes: bytes, source_str: str) -> List[LoopInfo]:
    """Extract all loops from a function body, in source order."""
    loops = []

    # Find all loop nodes (for, while, do)
    for loop_type in ['for_statement', 'while_statement', 'do_statement']:
        for loop_node in _find_all_nodes_of_type(body_node, loop_type):
            loop_info = _extract_loop_info(loop_node, source_bytes, source_str, loop_type)
            loops.append(loop_info)

    # Sort by position to maintain order
    loops.sort(key=lambda l: l.byte_position)

    return loops


def _extract_loop_info(loop_node: Node, source_bytes: bytes, source_str: str, loop_type: str) -> LoopInfo:
    """Extract information about a loop."""

    # Determine simple loop type
    if loop_type == 'for_statement':
        simple_type = 'for'
    elif loop_type == 'while_statement':
        simple_type = 'while'
    else:
        simple_type = 'do'

    # Extract loop header
    header = _get_loop_header(loop_node, source_bytes, simple_type)

    # Position information
    byte_pos = loop_node.start_byte
    line_num = source_str[:byte_pos].count('\n') + 1

    return LoopInfo(
        type=simple_type,
        header=header,
        byte_position=byte_pos,
        line_number=line_num
    )


def _get_loop_header(loop_node: Node, source_bytes: bytes, loop_type: str) -> str:
    """Extract the loop header (everything before the body)."""

    # Find the body (compound_statement or single statement)
    body_start = None
    for child in loop_node.children:
        if child.type == 'compound_statement':
            body_start = child.start_byte
            break
        # For single-statement bodies, find the last child that's a statement
        if child.type in ['expression_statement', 'return_statement', 'for_statement',
                         'while_statement', 'if_statement', 'do_statement']:
            body_start = child.start_byte

    if body_start:
        header_bytes = source_bytes[loop_node.start_byte:body_start]
        header = header_bytes.decode('utf8').strip()
    else:
        # Fallback: whole loop text
        header = source_bytes[loop_node.start_byte:loop_node.end_byte].decode('utf8').strip()

    # Normalize whitespace
    import re
    header = re.sub(r'\s+', ' ', header)

    return header


# ============================================================================
# Step 2: Validate skeleton vs completion
# ============================================================================

def validate_completion_matches_skeleton(skeleton: str, completion: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that the model's completion matches the skeleton structure.

    This should be called BEFORE attempting injection.

    Returns:
        (is_valid, error_message)
    """

    skel_structure = extract_structure(skeleton)
    comp_structure = extract_structure(completion)

    # Compare structures
    return _compare_structures(skel_structure, comp_structure)


def _compare_structures(skel: CodeStructure, comp: CodeStructure) -> Tuple[bool, Optional[str]]:
    """Compare two code structures for compatibility."""

    # Check function count
    if len(skel.functions) != len(comp.functions):
        return False, f"Function count mismatch: skeleton has {len(skel.functions)}, completion has {len(comp.functions)}"

    # Check each function
    for i, (skel_func, comp_func) in enumerate(zip(skel.functions, comp.functions)):

        # Check function name
        if skel_func.name != comp_func.name:
            return False, f"Function {i} name mismatch: '{skel_func.name}' vs '{comp_func.name}'"

        # Check signature (normalized)
        if skel_func.signature != comp_func.signature:
            return False, f"Function '{skel_func.name}' signature mismatch:\n  Skeleton: {skel_func.signature}\n  Completion: {comp_func.signature}"

        # Check loop count
        if len(skel_func.loops) != len(comp_func.loops):
            return False, f"Function '{skel_func.name}' loop count mismatch: skeleton has {len(skel_func.loops)}, completion has {len(comp_func.loops)}"

        # Check each loop
        for j, (skel_loop, comp_loop) in enumerate(zip(skel_func.loops, comp_func.loops)):

            # Check loop type
            if skel_loop.type != comp_loop.type:
                return False, f"Function '{skel_func.name}' loop {j} type mismatch: '{skel_loop.type}' vs '{comp_loop.type}'"

            # Check loop header (optional - can be strict or lenient)
            if skel_loop.header != comp_loop.header:
                # This could be a warning rather than error if you want to be lenient
                return False, f"Function '{skel_func.name}' loop {j} header mismatch:\n  Skeleton: {skel_loop.header}\n  Completion: {comp_loop.header}"

    return True, None


# ============================================================================
# Step 3: Use tree-sitter for precise injection
# ============================================================================

@dataclass
class InjectionPoint:
    """Represents a point where an ACSL spec should be injected."""
    type: str  # 'function' or 'loop'
    byte_position: int  # Where to inject in the source
    line_number: int
    spec_index: int  # Which index in the spec array to use
    context: str  # Human-readable context (function name or loop description)


def find_injection_points(c_code: str, spec: List) -> List[InjectionPoint]:
    """
    Use tree-sitter to find exact positions where ACSL specs should be injected.

    This is more precise than regex-based approaches.

    Args:
        c_code: The C code (without ACSL specs)
        spec: The spec array [predicates, func1_spec, loop1_spec, ..., func2_spec, ...]

    Returns:
        List of InjectionPoint objects in reverse order (for easier injection)
    """

    structure = extract_structure(c_code)
    injection_points = []

    # spec[0] is predicates, spec[1:] are function/loop specs
    spec_index = 1  # Start from spec[1]

    for func in structure.functions:
        # Add injection point for function spec
        if spec_index < len(spec):
            injection_points.append(InjectionPoint(
                type='function',
                byte_position=func.byte_position,
                line_number=func.line_number,
                spec_index=spec_index,
                context=f"function '{func.name}'"
            ))
            spec_index += 1

        # Add injection points for each loop in this function
        for loop_idx, loop in enumerate(func.loops):
            if spec_index < len(spec):
                injection_points.append(InjectionPoint(
                    type='loop',
                    byte_position=loop.byte_position,
                    line_number=loop.line_number,
                    spec_index=spec_index,
                    context=f"loop {loop_idx} in function '{func.name}' ({loop.type} loop)"
                ))
                spec_index += 1

    # Sort in reverse order for easier injection (inject from end to start)
    injection_points.sort(key=lambda p: p.byte_position, reverse=True)

    return injection_points


def inject_acsl_specs_treesitter(spec: List, c_code: str) -> str:
    """
    Inject ACSL specs using tree-sitter for precise positioning.

    This is more reliable than regex-based injection.
    """
    import re

    if not spec or len(spec) <= 1:
        return c_code

    # Step 1: Find where #include statements end (if any)
    include_pattern = r'^\s*#\s*include\s+[<"][^>"]+[>"]'
    lines = c_code.split('\n')
    last_include_line = -1

    for i, line in enumerate(lines):
        if re.match(include_pattern, line):
            last_include_line = i

    # Step 2: Split the code into header (includes) and body (everything else)
    if last_include_line >= 0:
        header_lines = lines[:last_include_line + 1]
        body_lines = lines[last_include_line + 1:]
        header = '\n'.join(header_lines)
        body = '\n'.join(body_lines)
    else:
        header = ""
        body = c_code

    # Step 3: Add predicates after header
    predicates = spec[0] if spec[0] else []
    predicates_text = ""
    if predicates:
        predicates_text = "\n\n".join(pred.strip() for pred in predicates if pred and pred.strip())

    # Step 4: Find injection points in the body (not the full code)
    injection_points = find_injection_points(body, spec)

    # Step 5: Inject function/loop specs in reverse order
    result = body
    for point in injection_points:
        spec_text = spec[point.spec_index]

        if spec_text and spec_text.strip():
            # Insert spec before the injection point
            result = (
                result[:point.byte_position] +
                spec_text.strip() + '\n' +
                result[point.byte_position:]
            )

    # Step 6: Reassemble: header + predicates + body with specs
    final_parts = []
    if header:
        final_parts.append(header)
    if predicates_text:
        final_parts.append(predicates_text)
    final_parts.append(result)

    final = '\n\n'.join(final_parts)

    # Clean up excessive newlines
    final = re.sub(r'\n\s*\n\s*\n+', '\n\n', final)

    return final.strip()


# ============================================================================
# Step 4: Complete validation + injection workflow
# ============================================================================

def validate_and_inject(
    skeleton: str,
    completion: str,
    spec: List
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Complete workflow: validate structure, then inject specs.

    Returns:
        (success, injected_code, error_message)
    """

    # Step 1: Validate that completion matches skeleton
    valid, error = validate_completion_matches_skeleton(skeleton, completion)

    if not valid:
        return False, None, f"Validation failed: {error}"

    # Step 2: Inject specs using tree-sitter
    try:
        injected = inject_acsl_specs_treesitter(spec, completion)
        return True, injected, None
    except Exception as e:
        return False, None, f"Injection failed: {str(e)}"


# ============================================================================
# Utility functions for debugging/analysis
# ============================================================================

def print_structure_comparison(skeleton: str, completion: str):
    """Print a detailed comparison of skeleton and completion structures."""

    print("=" * 70)
    print("SKELETON STRUCTURE")
    print("=" * 70)
    skel_structure = extract_structure(skeleton)
    print_structure(skel_structure)

    print("\n" + "=" * 70)
    print("COMPLETION STRUCTURE")
    print("=" * 70)
    comp_structure = extract_structure(completion)
    print_structure(comp_structure)

    print("\n" + "=" * 70)
    print("VALIDATION")
    print("=" * 70)
    valid, error = _compare_structures(skel_structure, comp_structure)
    if valid:
        print("✓ Structures match!")
    else:
        print(f"✗ Validation failed: {error}")


def print_structure(structure: CodeStructure):
    """Pretty print a code structure."""
    for i, func in enumerate(structure.functions):
        print(f"\nFunction {i}: {func.name}")
        print(f"  Signature: {func.signature}")
        print(f"  Line: {func.line_number}")
        print(f"  Loops: {len(func.loops)}")
        for j, loop in enumerate(func.loops):
            print(f"    Loop {j}: {loop.type}")
            print(f"      Header: {loop.header}")
            print(f"      Line: {loop.line_number}")


if __name__ == '__main__':
    # Example usage

    skeleton = """int clamp(int v, int min, int max) {
    // TODO: implementation
}

int min_index(int* t, int n) {
    while(i < n-1) {
        // TODO: implementation
    }
    // TODO: implementation
}"""

    # Good completion (matches skeleton)
    good_completion = """int clamp(int v, int min, int max) {
    int low = v > min ? v : min;
    return low < max ? low : max;
}

int min_index(int* t, int n) {
    int minInd = 0, i = 0;
    while(i < n-1) {
        if (t[++i] < t[minInd])
            minInd = i;
    }
    return minInd;
}"""

    # Bad completion (different structure)
    bad_completion = """int clamp(int v, int min, int max) {
    for (int i = 0; i < 10; i++) {  // Added a loop!
        printf("test");
    }
    return v;
}

int min_index(int* t, int n) {
    return 0;
}"""

    spec = [
        [],  # No predicates
        '/*@ requires v >= min && v <= max;\n    ensures \\result == v;\n */',
        '/*@\n      loop invariant 0 <= i < n;\n      loop variant n-1-i;\n     */'
    ]

    print("Testing GOOD completion:")
    print_structure_comparison(skeleton, good_completion)

    success, injected, error = validate_and_inject(skeleton, good_completion, spec)
    if success:
        print("\n" + "=" * 70)
        print("INJECTED CODE")
        print("=" * 70)
        print(injected)
    else:
        print(f"\nError: {error}")

    print("\n\n")
    print("Testing BAD completion:")
    print_structure_comparison(skeleton, bad_completion)

    success, injected, error = validate_and_inject(skeleton, bad_completion, spec)
    if not success:
        print(f"\n✓ Correctly rejected: {error}")
