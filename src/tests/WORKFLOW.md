# Tree-sitter Based ACSL Injection Workflow

## The Problem

1. **Skeleton validation**: How do we verify the model's completion follows the skeleton?
2. **Spec injection**: How do we ensure specs go in the right place?

## The Solution: Use Tree-sitter Throughout

Tree-sitter gives us **precise AST-based positions** instead of fragile regex matching.

---

## Workflow Steps

### Step 1: Create Skeleton (existing)

```python
from skeleton_treesitter import create_skeleton

skeleton = create_skeleton(original_code_with_acsl)
# Result: Code with "// TODO: implementation" instead of actual code
```

**What this does:**
- Preserves function signatures
- Preserves loop headers (for/while/do)
- Removes implementation details
- Keeps ACSL comments for extraction

---

### Step 2: Extract Specs AND Structure Metadata (NEW)

```python
from extraction_treesitter import extract_specs
from validation_treesitter import extract_structure

# Extract specs (your existing approach)
spec_array = extract_specs(original_code_with_acsl)
# spec_array = [predicates, func1_spec, loop1_1_spec, func2_spec, ...]

# Extract structure metadata using tree-sitter
skeleton_structure = extract_structure(skeleton)
# skeleton_structure contains:
#   - Function names, signatures, positions
#   - Loop types, headers, positions (in order within each function)
```

**Why both?**
- `spec_array`: The ACSL contracts to inject
- `skeleton_structure`: The expected structure to validate against

---

### Step 3: Model Generates Completion

```python
# Your RLVR model generates code based on skeleton
completion = model.generate(skeleton)
```

---

### Step 4: Validate Completion Structure (BEFORE injection)

```python
from validation_treesitter import validate_completion_matches_skeleton

valid, error = validate_completion_matches_skeleton(skeleton, completion)

if not valid:
    # Reject this completion - structure doesn't match!
    # Give negative reward or regenerate
    print(f"Invalid completion: {error}")
    return NEGATIVE_REWARD
```

**What this checks:**
1. ✓ Same number of functions
2. ✓ Same function names and signatures
3. ✓ Same number of loops in each function
4. ✓ Same loop types (for/while/do) in same order
5. ✓ Same loop headers

**Example of what gets caught:**
- Model added an extra function → INVALID
- Model changed loop from `for` to `while` → INVALID
- Model added a loop that wasn't in skeleton → INVALID
- Model changed function signature → INVALID

---

### Step 5: Inject Specs Using Tree-sitter (if valid)

```python
from validation_treesitter import inject_acsl_specs_treesitter

if valid:
    injected_code = inject_acsl_specs_treesitter(spec_array, completion)
```

**How this works differently:**
- Uses AST positions instead of regex
- Finds exact byte position of each function/loop
- Injects specs at precise positions
- Much more reliable than pattern matching

---

## Key Differences: Function Specs vs Loop Invariants

Tree-sitter treats them **differently** because they ARE different AST nodes:

### Function Specs (Preconditions/Postconditions)

```c
/*@ requires v >= min && v <= max;    ← Function spec
    ensures \result == v;
 */
int clamp(int v, int min, int max) {  ← function_definition node
    // ...
}
```

**Tree-sitter approach:**
1. Find `function_definition` node
2. Get `func.byte_position` (where function starts)
3. Inject spec **right before** this position

**Code:**
```python
# In find_injection_points()
for func in structure.functions:
    injection_points.append(InjectionPoint(
        type='function',
        byte_position=func.byte_position,  # Start of function
        spec_index=spec_index,
        context=f"function '{func.name}'"
    ))
```

---

### Loop Invariants

```c
int min_index(int* t, int n) {
    int minInd = 0, i = 0;
    /*@ loop invariant 0 <= i < n;     ← Loop invariant
        loop variant n-1-i;
     */
    while(i < n-1) {                   ← while_statement node
        // ...
    }
}
```

**Tree-sitter approach:**
1. For each function, find its `compound_statement` (body)
2. Within that body, find all `for_statement`, `while_statement`, `do_statement` nodes
3. For each loop, get `loop.byte_position`
4. Inject invariant **right before** each loop position
5. **CRITICAL**: Loops are ordered by byte position to maintain order

**Code:**
```python
# In _extract_loops_from_body()
for loop_type in ['for_statement', 'while_statement', 'do_statement']:
    for loop_node in _find_all_nodes_of_type(body_node, loop_type):
        loop_info = _extract_loop_info(loop_node, ...)
        loops.append(loop_info)

# Sort by position to maintain order
loops.sort(key=lambda l: l.byte_position)
```

**Why this matters:**
- If function has 2 loops, we need to inject invariants in the correct order
- Tree-sitter guarantees we find loops in source order
- No guessing about "which loop comes first"

---

## Example: Walking Through a Complex Case

### Original Code with ACSL
```c
/*@ predicate sorted(int* a, int len) =
      \forall int i; 0 <= i < len-1 ==> a[i] <= a[i+1];
 */

/*@ requires n > 0;
    ensures 0 <= \result < n;
 */
int min_index(int* t, int n) {
    int minInd = 0;
    /*@ loop invariant 0 <= i <= n;
        loop variant n - i;
     */
    for (int i = 1; i < n; i++) {
        if (t[i] < t[minInd]) minInd = i;
    }
    return minInd;
}

/*@ requires n > 1;
    requires sorted(t, n);
    ensures \result == -1 || t[\result] == val;
 */
int binary_search(int* t, int n, int val) {
    int low = 0, high = n - 1;
    /*@ loop invariant 0 <= low <= high < n;
        loop variant high - low;
     */
    while (low <= high) {
        int mid = (low + high) / 2;
        if (t[mid] == val) return mid;
        /*@ loop invariant 0 <= i <= mid;
            loop variant mid - i;
         */
        for (int i = 0; i < mid; i++) {
            // some nested loop
        }
        if (t[mid] < val) low = mid + 1;
        else high = mid - 1;
    }
    return -1;
}
```

### Step-by-step Processing

#### 1. Extract structure:
```python
structure = extract_structure(code)

# Result:
structure.functions = [
    FunctionInfo(
        name='min_index',
        signature='int min_index(int* t, int n)',
        loops=[
            LoopInfo(type='for', header='for (int i = 1; i < n; i++)', ...)
        ]
    ),
    FunctionInfo(
        name='binary_search',
        signature='int binary_search(int* t, int n, int val)',
        loops=[
            LoopInfo(type='while', header='while (low <= high)', ...),
            LoopInfo(type='for', header='for (int i = 0; i < mid; i++)', ...)
        ]
    )
]
```

#### 2. Extract specs:
```python
spec = [
    ['/*@ predicate sorted(...) */'],  # spec[0]: predicates
    '/*@ requires n > 0; ... */',       # spec[1]: min_index function spec
    '/*@ loop invariant 0 <= i <= n; ... */',  # spec[2]: min_index for loop
    '/*@ requires n > 1; ... */',       # spec[3]: binary_search function spec
    '/*@ loop invariant 0 <= low ... */',      # spec[4]: binary_search while loop
    '/*@ loop invariant 0 <= i <= mid; ... */' # spec[5]: binary_search for loop (nested)
]
```

#### 3. Model generates completion (skeleton → implementation)

#### 4. Validate:
```python
# Tree-sitter checks:
# ✓ Found 2 functions: min_index, binary_search
# ✓ min_index has 1 loop (for)
# ✓ binary_search has 2 loops (while, then for)
# ✓ Signatures match
# ✓ Loop types match
```

#### 5. Inject using positions:
```python
injection_points = [
    InjectionPoint(type='function', spec_index=1, context='min_index'),
    InjectionPoint(type='loop', spec_index=2, context='for loop in min_index'),
    InjectionPoint(type='function', spec_index=3, context='binary_search'),
    InjectionPoint(type='loop', spec_index=4, context='while loop in binary_search'),
    InjectionPoint(type='loop', spec_index=5, context='for loop in binary_search'),
]

# Inject in reverse order to preserve byte positions
```

---

## Why This Approach is Better

### Old Regex Approach
```python
# Fragile regex matching
func_pattern = r'((?:static\s+)?(?:\w+\s*\*?\s+)(\w+)\s*\([^)]*\)\s*\{)'
loop_pattern = r'\bwhile\s*\('
```

**Problems:**
- ❌ Can match things in comments or strings
- ❌ Doesn't understand nesting
- ❌ Can't distinguish function declaration from definition
- ❌ Loop order depends on regex match order (unreliable)

### New Tree-sitter Approach
```python
# AST-based
func_node = find_node_of_type('function_definition')
loop_nodes = find_nodes_of_type('while_statement')
```

**Benefits:**
- ✅ Understands C syntax perfectly
- ✅ Handles nested structures correctly
- ✅ Gives exact byte positions
- ✅ Guarantees source order
- ✅ Never confused by comments/strings

---

## Summary: When to Use Tree-sitter

1. **During skeleton creation** (you already do this in `skeleton_treesitter.py`)
   - To identify function boundaries
   - To identify loop structures

2. **After extraction** (NEW)
   - To extract structure metadata alongside specs

3. **After model generation** (NEW - CRITICAL)
   - To validate completion matches skeleton
   - BEFORE attempting injection

4. **During injection** (NEW)
   - To find exact injection points
   - Instead of regex-based positioning
