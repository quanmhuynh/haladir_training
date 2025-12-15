import modal
import subprocess
import tempfile
import os
import re


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "build-essential",
        "gcc",
        "make",
        "curl",
        "wget",
        "ocaml",
        "opam",
        "libgmp-dev",
        "libmpfr-dev",
        "pkg-config",
        "graphviz",
        "libcairo2-dev",
        "libexpat1-dev",
        "libgtk-3-dev",
        "libgtksourceview-3.0-dev",
        "zlib1g-dev",
    )
    .run_commands(
        "opam init --disable-sandboxing -y",
        "opam update",
        "opam install -y frama-c alt-ergo why3 --assume-depexts",
        "ln -sf /root/.opam/default/bin/frama-c /usr/local/bin/frama-c",
        "ln -sf /root/.opam/default/bin/alt-ergo /usr/local/bin/alt-ergo",
        "ln -sf /root/.opam/default/bin/why3 /usr/local/bin/why3",
        "eval $(opam env) && why3 config detect",
    )
)

app = modal.App("frama_check", image=image)

@app.function(
    max_containers=50,
    timeout=30,
)
def check_frama_c_verification(acsl_spec: str, c_code: str) -> bool:
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
            f.write(f"{acsl_spec}\n\n{c_code}")
            temp_filename = f.name

        result = subprocess.run(
            ["frama-c", "-wp", "-wp-prover", "alt-ergo", "-wp-timeout", "10", temp_filename],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stdout + result.stderr

        print("=" * 80)
        print("FRAMA-C OUTPUT:")
        print(output)
        print("=" * 80)

        os.unlink(temp_filename)

        match = re.search(r'Proved goals:\s+(\d+)\s*/\s*(\d+)', output)
        if match:
            proved = int(match.group(1))
            total = int(match.group(2))
            print(f"Proved: {proved}/{total}")
            return proved == total and proved > 0

        return False

    except Exception as e:
        print(f"Verification error: {e}")
        return False


@app.function(max_containers=50, timeout=120)
def reinject_and_verify(spec: list, c_code: str) -> float:
    """
    Reinject ACSL specs into C code and verify.
    spec: [predicates_list, spec1_string, spec2_string, ...]
    c_code: the C code without specs

    Returns: float between 0 and 1 (proved/total ratio), or 0.0 on failure
    """
    try:
        # DEBUG: Print input types and values
        print("=" * 80)
        print("DEBUG INPUT:")
        print(f"spec type: {type(spec)}")
        print(f"spec length: {len(spec) if spec else 0}")
        print(f"spec raw value: {repr(spec)[:500]}...")  # First 500 chars
        print(f"c_code type: {type(c_code)}")
        print(f"c_code length: {len(c_code) if c_code else 0}")
        print(f"c_code first 200 chars: {repr(c_code[:200]) if c_code else 'None'}")
        print("=" * 80)

        # Handle empty or invalid spec
        if not spec or len(spec) == 0:
            print("No specs to inject")
            return 0.0

        # Extract predicates and function specs
        predicates = spec[0]  # List of predicate strings
        function_specs = spec[1:] if len(spec) > 1 else []  # List of function spec strings

        # DEBUG: Print extracted parts
        print("=" * 80)
        print("DEBUG EXTRACTED:")
        print(f"predicates type: {type(predicates)}")
        print(f"predicates value: {repr(predicates)[:300]}...")
        print(f"function_specs count: {len(function_specs)}")
        if function_specs:
            print(f"first function_spec: {repr(function_specs[0])[:200]}...")
        print("=" * 80)

        # Step 1: Build predicates section
        predicates_text = "\n\n".join(predicates) if predicates else ""

        # Step 2: Find all function definitions in c_code
        function_pattern = r'((?:static\s+|extern\s+|inline\s+)?(?:\w+\s*\*?\s+)(\w+)\s*\([^)]*\)\s*\{)'
        matches = list(re.finditer(function_pattern, c_code))

        if len(matches) != len(function_specs):
            print(f"Warning: Found {len(matches)} functions but have {len(function_specs)} specs")

        # Step 3: Inject specs before each function (in reverse to maintain positions)
        injected_code = c_code

        # Go through matches in reverse order to preserve string positions
        for i in range(len(matches) - 1, -1, -1):
            if i < len(function_specs):
                match = matches[i]
                spec_text = function_specs[i]
                insert_pos = match.start()

                # Insert spec before function
                injected_code = (
                    injected_code[:insert_pos]
                    + spec_text
                    + "\n"
                    + injected_code[insert_pos:]
                )

        # Step 4: Combine predicates at top with injected code
        full_code = ""
        if predicates_text:
            full_code += predicates_text + "\n\n"
        full_code += injected_code

        # DEBUG: Print the final injected code
        print("=" * 80)
        print("DEBUG FULL CODE TO VERIFY:")
        print(full_code)
        print("=" * 80)

        # Step 5: Write to temporary file and verify with Frama-C
        with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
            f.write(full_code)
            temp_filename = f.name

        result = subprocess.run(
            ["frama-c", "-wp", "-wp-prover", "alt-ergo", "-wp-timeout", "10", temp_filename],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stdout + result.stderr
        print("=" * 80)
        print("FRAMA-C OUTPUT:")
        print(output)
        print("=" * 80)

        os.unlink(temp_filename)

        # Step 6: Parse results
        match = re.search(r'Proved goals:\s+(\d+)\s*/\s*(\d+)', output)
        if match:
            proved = int(match.group(1))
            total = int(match.group(2))
            print(f"Proved: {proved}/{total}")
            if proved > 0 and total > 0:
                return proved / total
            return 0.0

        return 0.0

    except Exception as e:
        print(f"Verification error: {e}")
        return 0.0

@app.function(max_containers=50, timeout=120)
def verify_annotated_c(annotated_code: str, verbose: bool = True) -> bool:
    try:
        # Print input code with line numbers
        if verbose:
            print("=" * 80)
            print("INPUT CODE:")
            print("=" * 80)
            for i, line in enumerate(annotated_code.split('\n'), 1):
                print(f"{i:4d} | {line}")
            print("=" * 80)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
            f.write(annotated_code)
            temp_filename = f.name

        result = subprocess.run(
            ["frama-c", "-wp", "-wp-prover", "alt-ergo", "-wp-timeout", "10", temp_filename],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stdout + result.stderr

        if verbose:
            print("\nFRAMA-C FULL OUTPUT:")
            print("=" * 80)
            print(output)
            print("=" * 80)

        # Extract and print errors/warnings
        errors = re.findall(r'^\[.*?\] .*(?:error|warning|Error|Warning).*$', output, re.MULTILINE)
        failed_goals = re.findall(r'^\[wp\].*Goal.*not proved.*$', output, re.MULTILINE)
        
        if errors:
            print("\n⚠️  ERRORS/WARNINGS:")
            print("-" * 40)
            for err in errors:
                print(f"  {err}")
        
        if failed_goals:
            print("\n❌ FAILED GOALS:")
            print("-" * 40)
            for goal in failed_goals:
                print(f"  {goal}")

        os.unlink(temp_filename)

        # Parse proved goals
        match = re.search(r'Proved goals:\s+(\d+)\s*/\s*(\d+)', output)
        if match:
            proved = int(match.group(1))
            total = int(match.group(2))
            status = "✅ PASSED" if (proved == total and proved > 0) else "❌ FAILED"
            print(f"\n{status}: Proved {proved}/{total} goals")
            return proved == total and proved > 0

        print("\n❌ FAILED: Could not parse Frama-C output (no goals found)")
        return False

    except subprocess.TimeoutExpired:
        print("\n❌ FAILED: Frama-C timed out after 60 seconds")
        return False
    except Exception as e:
        print(f"\n❌ FAILED: Verification error: {e}")
        import traceback
        traceback.print_exc()
        return False

